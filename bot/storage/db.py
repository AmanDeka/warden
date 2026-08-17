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

CREATE_INDEXED_CHANNELS = """
CREATE TABLE IF NOT EXISTS indexed_channels (
    channel_id INTEGER PRIMARY KEY,
    guild_id   INTEGER NOT NULL,
    added_at   TEXT NOT NULL
);
"""

CREATE_MESSAGE_EMBEDDINGS = """
CREATE TABLE IF NOT EXISTS message_embeddings (
    message_id INTEGER PRIMARY KEY,
    embedding  TEXT NOT NULL   -- JSON array of floats
);
"""

# Generic key/value store for runtime-configurable bot settings.
CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULTS: dict[str, str] = {
    "search_method": "fts",  # 'fts' | 'semantic'
}


async def init() -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(CREATE_MESSAGES)
        await conn.execute(CREATE_MESSAGES_FTS)
        await conn.execute(CREATE_AUDIT_LOG)
        await conn.execute(CREATE_CONVERSATION_CONTEXT)
        await conn.execute(CREATE_PERMISSION_ALLOWLIST)
        await conn.execute(CREATE_INDEXED_CHANNELS)
        await conn.execute(CREATE_MESSAGE_EMBEDDINGS)
        await conn.execute(CREATE_SETTINGS)
        for key, value in DEFAULTS.items():
            await conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, value),
            )
        await conn.commit()


async def get_setting(key: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            (key, value),
        )
        await conn.commit()


def connect() -> aiosqlite.Connection:
    return aiosqlite.connect(DB_PATH)


# ---------------------------------------------------------------------------
# Indexed channels — in-memory cache so every on_message doesn't hit the DB
# ---------------------------------------------------------------------------

_indexed_channel_ids: set[int] | None = None  # None = not yet loaded


def _invalidate_channel_cache() -> None:
    global _indexed_channel_ids
    _indexed_channel_ids = None


async def get_indexed_channel_ids() -> set[int]:
    """Return the set of channel IDs to index.

    An empty set means no whitelist is configured — index all channels.
    """
    global _indexed_channel_ids
    if _indexed_channel_ids is None:
        async with aiosqlite.connect(DB_PATH) as conn:
            async with conn.execute("SELECT channel_id FROM indexed_channels") as cursor:
                rows = await cursor.fetchall()
        _indexed_channel_ids = {row[0] for row in rows}
    return _indexed_channel_ids


async def add_indexed_channel(channel_id: int, guild_id: int) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO indexed_channels(channel_id, guild_id, added_at) VALUES (?, ?, ?)",
            (channel_id, guild_id, now),
        )
        await conn.commit()
    _invalidate_channel_cache()


async def remove_indexed_channel(channel_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "DELETE FROM indexed_channels WHERE channel_id = ?",
            (channel_id,),
        )
        await conn.commit()
    _invalidate_channel_cache()


# ---------------------------------------------------------------------------
# Permission allowlist — in-memory cache mirrors indexed_channels pattern
# ---------------------------------------------------------------------------

_allowlist_role_ids: set[int] | None = None  # None = not yet loaded


def _invalidate_allowlist_cache() -> None:
    global _allowlist_role_ids
    _allowlist_role_ids = None


async def get_allowlist_role_ids() -> set[int]:
    global _allowlist_role_ids
    if _allowlist_role_ids is None:
        async with aiosqlite.connect(DB_PATH) as conn:
            async with conn.execute("SELECT role_id FROM permission_allowlist") as cursor:
                rows = await cursor.fetchall()
        _allowlist_role_ids = {row[0] for row in rows}
    return _allowlist_role_ids


async def add_allowlist_role(role_id: int, guild_id: int, added_by: int) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO permission_allowlist(role_id, guild_id, added_by, added_at)"
            " VALUES (?, ?, ?, ?)",
            (role_id, guild_id, added_by, now),
        )
        await conn.commit()
    _invalidate_allowlist_cache()


async def remove_allowlist_role(role_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "DELETE FROM permission_allowlist WHERE role_id = ?",
            (role_id,),
        )
        await conn.commit()
    _invalidate_allowlist_cache()


async def get_allowlist_entries() -> list[dict]:
    """Return full rows for the /list command (role_id, added_by, added_at)."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT role_id, added_by, added_at FROM permission_allowlist ORDER BY added_at"
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]
