"""Chunked history fetch helpers."""

from __future__ import annotations
from typing import AsyncIterator
import discord

CHUNK_SIZE = 100


async def iter_history(
    channel: discord.TextChannel,
    limit: int | None = None,
) -> AsyncIterator[discord.Message]:
    """Yield messages in descending order, respecting Discord rate limits."""
    fetched = 0
    async for message in channel.history(limit=limit, oldest_first=False):
        yield message
        fetched += 1
        if limit and fetched >= limit:
            break
