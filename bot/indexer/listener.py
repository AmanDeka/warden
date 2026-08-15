"""Gateway event hooks: on_message / on_message_edit / on_message_delete (no LLM)."""

import discord
from bot.storage import db


async def on_message(message: discord.Message) -> None:
    # TODO: write to messages index
    pass


async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
    # TODO: update indexed content
    pass


async def on_message_delete(message: discord.Message) -> None:
    # TODO: soft-delete (set deleted_at)
    pass


async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent) -> None:
    # TODO: soft-delete for messages not in local cache
    pass
