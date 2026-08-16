"""Tool: summarize_channel — pull a message range from the index."""

from __future__ import annotations

from datetime import datetime

from bot.storage import db


async def summarize_channel(
    channel_id: int,
    since: datetime | None = None,
    limit: int = 200,
) -> list[dict]:
    """Fetch up to `limit` messages from the index (oldest-first) for Gemini to summarize.

    Returns raw message rows; the orchestrator feeds these to Gemini which writes
    the final structured summary as its response.
    """
    sql = """
        SELECT message_id, author_id, content, created_at
        FROM messages
        WHERE channel_id = ?
          AND deleted_at IS NULL
          AND content != ''
    """
    params: list = [channel_id]

    if since is not None:
        sql += " AND created_at >= ?"
        params.append(since.isoformat())

    sql += " ORDER BY created_at ASC LIMIT ?"
    params.append(limit)

    async with db.connect() as conn:
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

    return [
        {
            "message_id": row[0],
            "author_id": row[1],
            "content": row[2],
            "created_at": row[3],
        }
        for row in rows
    ]
