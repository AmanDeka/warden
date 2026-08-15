"""One-time throttled history backfill per channel on bot join / startup."""

import asyncio

import discord

from bot.indexer.listener import write_message
from bot.storage import db

BACKFILL_DELAY = 0.5  # seconds between channels, to respect rate limits
BATCH_DELAY = 0.25  # seconds between write batches within a channel
BATCH_SIZE = 100


async def _last_indexed_message_id(channel_id: int) -> int | None:
    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT MAX(message_id) FROM messages WHERE channel_id = ?",
            (channel_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] is not None else None


async def backfill_channel(channel: discord.TextChannel) -> None:
    """Paginate the channel's full history and index any messages not yet stored.

    Resumes from the newest message_id already indexed for this channel (snowflake
    IDs are monotonically increasing), so re-running only fetches what's new and
    never re-inserts a row that's already there.
    """
    after_id = await _last_indexed_message_id(channel.id)
    after = discord.Object(id=after_id) if after_id is not None else None

    try:
        history = channel.history(limit=None, after=after, oldest_first=True)

        batch: list[discord.Message] = []
        async with db.connect() as conn:
            async for message in history:
                batch.append(message)
                if len(batch) >= BATCH_SIZE:
                    for m in batch:
                        await write_message(conn, m)
                    await conn.commit()
                    batch.clear()
                    await asyncio.sleep(BATCH_DELAY)

            if batch:
                for m in batch:
                    await write_message(conn, m)
                await conn.commit()
    except discord.Forbidden:
        print(f"Backfill skipped for #{channel.name}: missing read history permission")
    except discord.HTTPException as exc:
        print(f"Backfill failed for #{channel.name}: {exc}")


async def backfill_guild(guild: discord.Guild) -> None:
    for channel in guild.text_channels:
        await backfill_channel(channel)
        await asyncio.sleep(BACKFILL_DELAY)
