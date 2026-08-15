"""Tool: summarize_channel — pull a message range from the index and summarize."""

from __future__ import annotations
from datetime import datetime


async def summarize_channel(
    channel_id: int,
    since: datetime | None = None,
    limit: int = 200,
) -> str:
    # TODO: fetch from index, call Gemini for structured summary
    raise NotImplementedError
