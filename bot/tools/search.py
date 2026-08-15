"""Tools: search_messages, find_message_by_context — query the SQLite index."""

from __future__ import annotations
from bot.storage import db


async def search_messages(
    channel_id: int,
    query: str,
    author_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    # TODO: implement FTS5 query against messages table
    raise NotImplementedError


async def find_message_by_context(channel_id: int, description: str) -> dict | None:
    # TODO: pull candidates from index, re-rank with Gemini
    raise NotImplementedError
