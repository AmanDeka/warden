"""Shared fixtures and environment setup for all tests."""

import os

os.environ.setdefault("GUILD_ID", "111111111111111111")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("DISCORD_TOKEN", "test-token")

import pytest
from bot.storage import db


@pytest.fixture
async def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_file))
    monkeypatch.setattr(db, "_indexed_channel_ids", None)
    monkeypatch.setattr(db, "_allowlist_role_ids", None)
    await db.init()
    yield str(db_file)
