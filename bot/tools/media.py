"""Tool: find_media — query indexed attachments/embeds."""

from __future__ import annotations


async def find_media(
    channel_id: int,
    media_type: str = "image",
    query: str | None = None,
    limit: int = 200,
) -> list[dict]:
    # TODO: implement
    raise NotImplementedError
