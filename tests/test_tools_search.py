"""Tests for search tools (FTS backend)."""

from datetime import datetime, timezone

import pytest

from bot.storage import db
from bot.tools.search import _fts_escape, _row_to_dict, search_messages


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_fts_escape_basic():
    assert _fts_escape("hello") == '"hello"'


def test_fts_escape_quotes():
    assert _fts_escape('say "hi"') == '"say ""hi"""'


def test_fts_escape_empty():
    assert _fts_escape("") == '""'


def test_row_to_dict():
    row = (111, 222, 333, "hello world", "2026-01-01T00:00:00")
    result = _row_to_dict(row)
    assert result == {
        "message_id": 111,
        "channel_id": 222,
        "author_id": 333,
        "content": "hello world",
        "created_at": "2026-01-01T00:00:00",
    }


# ---------------------------------------------------------------------------
# FTS search with real DB
# ---------------------------------------------------------------------------

async def _insert_message(conn, message_id, guild_id, channel_id, author_id, content, deleted=False):
    now = datetime.now(timezone.utc).isoformat()
    deleted_at = now if deleted else None
    await conn.execute(
        "INSERT INTO messages(message_id, guild_id, channel_id, author_id, content, attachments, embeds, created_at, deleted_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (message_id, guild_id, channel_id, author_id, content, "[]", "[]", now, deleted_at),
    )
    if not deleted:
        await conn.execute(
            "INSERT INTO messages_fts(rowid, content) VALUES (?,?)",
            (message_id, content),
        )
    await conn.commit()


async def test_search_messages_fts_returns_match(tmp_db):
    async with db.connect() as conn:
        await _insert_message(conn, 1, 100, 200, 300, "the quick brown fox")

    results = await search_messages(channel_id=200, query="quick brown")
    assert len(results) == 1
    assert results[0]["message_id"] == 1
    assert results[0]["content"] == "the quick brown fox"


async def test_search_messages_fts_no_match(tmp_db):
    async with db.connect() as conn:
        await _insert_message(conn, 2, 100, 200, 300, "hello world")

    results = await search_messages(channel_id=200, query="unrelatedxyz")
    assert results == []


async def test_search_messages_fts_respects_channel(tmp_db):
    async with db.connect() as conn:
        await _insert_message(conn, 10, 100, 500, 300, "deploy success")
        await _insert_message(conn, 11, 100, 600, 300, "deploy failed")

    results = await search_messages(channel_id=500, query="deploy")
    assert len(results) == 1
    assert results[0]["channel_id"] == 500


async def test_search_messages_fts_excludes_deleted(tmp_db):
    async with db.connect() as conn:
        await _insert_message(conn, 20, 100, 700, 300, "secret message", deleted=True)

    results = await search_messages(channel_id=700, query="secret")
    assert results == []


async def test_search_messages_fts_author_filter(tmp_db):
    async with db.connect() as conn:
        await _insert_message(conn, 30, 100, 800, 101, "banana smoothie")
        await _insert_message(conn, 31, 100, 800, 102, "banana bread")

    results = await search_messages(channel_id=800, query="banana", author_id=101)
    assert len(results) == 1
    assert results[0]["author_id"] == 101
