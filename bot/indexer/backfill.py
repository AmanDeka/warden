"""One-time throttled history backfill per channel on bot join / startup."""

import asyncio
import discord
from bot.storage import db

BACKFILL_DELAY = 0.5  # seconds between batches to respect rate limits


async def backfill_channel(channel: discord.TextChannel) -> None:
    # TODO: paginate channel.history(limit=None) with throttling, write to index
    pass


async def backfill_guild(guild: discord.Guild) -> None:
    for channel in guild.text_channels:
        await backfill_channel(channel)
        await asyncio.sleep(BACKFILL_DELAY)
