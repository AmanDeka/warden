"""Embedding generation, storage, and similarity helpers."""

from __future__ import annotations

import asyncio
import json
import math

from google.genai import types

from bot.storage import db
from bot.utils.gemini import get_client

EMBEDDING_MODEL = "text-embedding-004"


async def get_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    """Call Gemini embedding API in a thread so it doesn't block the event loop."""
    client = get_client()
    result = await asyncio.to_thread(
        client.models.embed_content,
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type=task_type),
    )
    return list(result.embeddings[0].values)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


async def store_embedding(message_id: int, embedding: list[float]) -> None:
    async with db.connect() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO message_embeddings(message_id, embedding) VALUES (?, ?)",
            (message_id, json.dumps(embedding)),
        )
        await conn.commit()


async def fetch_channel_embeddings(
    channel_id: int,
    author_id: int | None = None,
) -> list[tuple[int, int, int, str, str, list[float]]]:
    """Return (message_id, channel_id, author_id, content, created_at, embedding)
    for all non-deleted messages in `channel_id` that have stored embeddings."""
    sql = """
        SELECT m.message_id, m.channel_id, m.author_id, m.content, m.created_at,
               me.embedding
        FROM message_embeddings me
        JOIN messages m ON m.message_id = me.message_id
        WHERE m.channel_id = ?
          AND m.deleted_at IS NULL
    """
    params: list = [channel_id]
    if author_id is not None:
        sql += " AND m.author_id = ?"
        params.append(author_id)

    async with db.connect() as conn:
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

    return [
        (row[0], row[1], row[2], row[3], row[4], json.loads(row[5]))
        for row in rows
    ]
