"""Tools: search_messages, find_message_by_context.

Two search backends are available and switchable at runtime via /search-mode:
  - fts      Full-text keyword search (SQLite FTS5, no API cost)
  - semantic  Embedding-based similarity search (Gemini text-embedding-004)

search_messages() reads the 'search_method' setting and routes accordingly.
find_message_by_context() always uses semantic (keyword search on a natural-language
description doesn't make sense), with FTS as a fallback when embeddings are absent.
"""

from __future__ import annotations

from bot.storage import db
from bot.tools.embeddings import cosine_similarity, fetch_channel_embeddings, get_embedding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fts_escape(query: str) -> str:
    # Phrase match: avoids FTS5 syntax errors on arbitrary input.
    return '"' + query.replace('"', '""') + '"'


def _row_to_dict(row: tuple) -> dict:
    return {
        "message_id": row[0],
        "channel_id": row[1],
        "author_id": row[2],
        "content": row[3],
        "created_at": row[4],
    }


# ---------------------------------------------------------------------------
# FTS backend
# ---------------------------------------------------------------------------

async def _search_fts(
    channel_id: int,
    query: str,
    author_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    sql = """
        SELECT m.message_id, m.channel_id, m.author_id, m.content, m.created_at
        FROM messages_fts
        JOIN messages m ON m.message_id = messages_fts.rowid
        WHERE messages_fts MATCH ?
          AND m.channel_id = ?
          AND m.deleted_at IS NULL
    """
    params: list = [_fts_escape(query), channel_id]

    if author_id is not None:
        sql += " AND m.author_id = ?"
        params.append(author_id)

    sql += " LIMIT ?"
    params.append(limit)

    async with db.connect() as conn:
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

    return [_row_to_dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Semantic backend
# ---------------------------------------------------------------------------

async def _search_semantic(
    channel_id: int,
    query: str,
    author_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    query_embedding = await get_embedding(query, task_type="RETRIEVAL_QUERY")
    candidates = await fetch_channel_embeddings(channel_id, author_id=author_id)

    if not candidates:
        # No embeddings stored yet — fall back to FTS transparently.
        return await _search_fts(channel_id, query, author_id=author_id, limit=limit)

    scored = [
        (cosine_similarity(query_embedding, row[5]), row)
        for row in candidates
    ]
    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        {
            "message_id": row[0],
            "channel_id": row[1],
            "author_id": row[2],
            "content": row[3],
            "created_at": row[4],
            "score": round(score, 4),
        }
        for score, row in scored[:limit]
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_messages(
    channel_id: int,
    query: str,
    author_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Route to FTS or semantic backend based on the current 'search_method' setting."""
    method = await db.get_setting("search_method") or "fts"
    if method == "semantic":
        return await _search_semantic(channel_id, query, author_id=author_id, limit=limit)
    return await _search_fts(channel_id, query, author_id=author_id, limit=limit)


async def find_message_by_context(channel_id: int, description: str) -> list[dict]:
    """Semantic search by natural-language description; falls back to FTS if no embeddings.

    Returns up to 20 candidates ranked by similarity — the orchestrator feeds these
    to Gemini which identifies the best match from conversation context.
    """
    query_embedding = await get_embedding(description, task_type="RETRIEVAL_QUERY")
    candidates = await fetch_channel_embeddings(channel_id)

    if candidates:
        scored = [
            (cosine_similarity(query_embedding, row[5]), row)
            for row in candidates
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "message_id": row[0],
                "channel_id": row[1],
                "author_id": row[2],
                "content": row[3],
                "created_at": row[4],
                "score": round(score, 4),
            }
            for score, row in scored[:20]
        ]

    # Fallback: FTS on the description keywords.
    return await _search_fts(channel_id, description, limit=20)
