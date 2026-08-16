"""Tool: find_media — query indexed attachments/embeds."""

from __future__ import annotations

import json

from bot.storage import db

# Maps the tool's media_type arg to a content-type prefix.
# "file" is a catch-all that matches any attachment regardless of type.
_CONTENT_TYPE_PREFIX: dict[str, str] = {
    "image": "image/",
    "video": "video/",
    "audio": "audio/",
    "file": "",
}


def _fts_escape(query: str) -> str:
    return '"' + query.replace('"', '""') + '"'


def _filter_attachments(attachments_json: str, prefix: str) -> list[dict]:
    attachments = json.loads(attachments_json)
    if not prefix:
        return attachments
    return [a for a in attachments if (a.get("content_type") or "").startswith(prefix)]


async def find_media(
    channel_id: int,
    media_type: str = "image",
    query: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Return messages containing attachments of the requested media_type.

    If `query` is given, restricts to FTS-matching messages first.
    Each result includes the message metadata and only the matching attachments.
    """
    prefix = _CONTENT_TYPE_PREFIX.get(media_type, f"{media_type}/")

    # Fetch a larger candidate set so we still hit `limit` after attachment filtering.
    fetch_limit = limit * 5

    if query:
        sql = """
            SELECT m.message_id, m.channel_id, m.author_id, m.content,
                   m.attachments, m.created_at
            FROM messages_fts
            JOIN messages m ON m.message_id = messages_fts.rowid
            WHERE messages_fts MATCH ?
              AND m.channel_id = ?
              AND m.deleted_at IS NULL
              AND m.attachments != '[]'
            LIMIT ?
        """
        params: list = [_fts_escape(query), channel_id, fetch_limit]
    else:
        sql = """
            SELECT message_id, channel_id, author_id, content,
                   attachments, created_at
            FROM messages
            WHERE channel_id = ?
              AND deleted_at IS NULL
              AND attachments != '[]'
            ORDER BY created_at DESC
            LIMIT ?
        """
        params = [channel_id, fetch_limit]

    async with db.connect() as conn:
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

    results: list[dict] = []
    for row in rows:
        matching = _filter_attachments(row[4], prefix)
        if not matching:
            continue
        results.append(
            {
                "message_id": row[0],
                "channel_id": row[1],
                "author_id": row[2],
                "content": row[3],
                "attachments": matching,
                "created_at": row[5],
            }
        )
        if len(results) >= limit:
            break

    return results
