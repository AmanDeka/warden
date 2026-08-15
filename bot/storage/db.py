"""SQLite (FTS5) setup and connection management."""

import aiosqlite
import os

DB_PATH = os.environ.get("DB_PATH", "warden.db")

CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS messages (
    message_id   INTEGER PRIMARY KEY,
    guild_id     INTEGER NOT NULL,
    channel_id   INTEGER NOT NULL,
    author_id    INTEGER NOT NULL,
    content      TEXT,
    attachments  TEXT,   -- JSON array
    embeds       TEXT,   -- JSON array
    created_at   TEXT NOT NULL,
    edited_at    TEXT,
    deleted_at   TEXT
);
"""

CREATE_MESSAGES_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='message_id'
);
"""

CREATE_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    tool_name    TEXT NOT NULL,
    args         TEXT,   -- JSON
    requester_id INTEGER NOT NULL,
    result       TEXT,
    executed_at  TEXT NOT NULL
);
"""

CREATE_CONVERSATION_CONTEXT = """
CREATE TABLE IF NOT EXISTS conversation_context (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    role         TEXT NOT NULL,   -- 'user' or 'model'
    content      TEXT NOT NULL,
    channel_id   INTEGER NOT NULL,
    created_at   TEXT NOT NULL
);
"""

CREATE_PERMISSION_ALLOWLIST = """
CREATE TABLE IF NOT EXISTS permission_allowlist (
    role_id    INTEGER PRIMARY KEY,
    guild_id   INTEGER NOT NULL,
    added_by   INTEGER NOT NULL,
    added_at   TEXT NOT NULL
);
"""


async def init() -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(CREATE_MESSAGES)
        await conn.execute(CREATE_MESSAGES_FTS)
        await conn.execute(CREATE_AUDIT_LOG)
        await conn.execute(CREATE_CONVERSATION_CONTEXT)
        await conn.execute(CREATE_PERMISSION_ALLOWLIST)
        await conn.commit()


def connect() -> aiosqlite.Connection:
    return aiosqlite.connect(DB_PATH)
