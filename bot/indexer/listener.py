"""Gateway event hooks: on_message / on_message_edit / on_message_delete (no LLM)."""

import json
from datetime import datetime, timezone

import discord

from bot.storage import db


def _serialize_attachments(message: discord.Message) -> str:
    return json.dumps(
        [{"url": a.url, "content_type": a.content_type} for a in message.attachments]
    )


def _serialize_embeds(message: discord.Message) -> str:
    return json.dumps([e.to_dict() for e in message.embeds])


async def on_message(message: discord.Message) -> None:
    if message.guild is None:
        return

    content = message.content or ""

    async with db.connect() as conn:
        await conn.execute(
            """
            INSERT INTO messages
                (message_id, guild_id, channel_id, author_id, content, attachments, embeds, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                content=excluded.content,
                attachments=excluded.attachments,
                embeds=excluded.embeds
            """,
            (
                message.id,
                message.guild.id,
                message.channel.id,
                message.author.id,
                content,
                _serialize_attachments(message),
                _serialize_embeds(message),
                message.created_at.isoformat(),
            ),
        )
        await conn.execute(
            "INSERT INTO messages_fts(rowid, content) VALUES (?, ?)",
            (message.id, content),
        )
        await conn.commit()


async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
    if after.guild is None:
        return

    now = datetime.now(timezone.utc).isoformat()
    new_content = after.content or ""

    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT content FROM messages WHERE message_id = ?", (after.id,)
        )
        row = await cursor.fetchone()
        old_content = row[0] if row is not None else ""

        await conn.execute(
            """
            INSERT INTO messages
                (message_id, guild_id, channel_id, author_id, content, attachments, embeds, created_at, edited_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                content=excluded.content,
                attachments=excluded.attachments,
                embeds=excluded.embeds,
                edited_at=excluded.edited_at
            """,
            (
                after.id,
                after.guild.id,
                after.channel.id,
                after.author.id,
                new_content,
                _serialize_attachments(after),
                _serialize_embeds(after),
                after.created_at.isoformat(),
                now,
            ),
        )

        if row is not None:
            await conn.execute(
                "INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', ?, ?)",
                (after.id, old_content),
            )
        await conn.execute(
            "INSERT INTO messages_fts(rowid, content) VALUES (?, ?)",
            (after.id, new_content),
        )
        await conn.commit()


async def _soft_delete(message_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with db.connect() as conn:
        await conn.execute(
            "UPDATE messages SET deleted_at = ? WHERE message_id = ? AND deleted_at IS NULL",
            (now, message_id),
        )
        await conn.commit()


async def on_message_delete(message: discord.Message) -> None:
    if message.guild is None:
        return
    await _soft_delete(message.id)


async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent) -> None:
    # Only handle deletes for messages that weren't already in the local cache
    # (those are covered by on_message_delete above) to avoid duplicate work.
    if payload.cached_message is not None:
        return
    if payload.guild_id is None:
        return
    await _soft_delete(payload.message_id)
