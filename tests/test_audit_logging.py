"""Tests for audit logging in the orchestrator.

Covers all four outcomes that must be written to audit_log:
  1. Successful tool execution
  2. Auth-denied write tool
  3. User-cancelled write tool
  4. Tool execution raises an exception
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import bot.agent.orchestrator as orch
from bot.storage import db


# ---------------------------------------------------------------------------
# _log_tool_call — DB insert
# ---------------------------------------------------------------------------

async def test_log_tool_call_writes_row(tmp_db, monkeypatch):
    monkeypatch.setattr(orch, "GUILD_ID", 111)
    monkeypatch.setattr(db, "DB_PATH", tmp_db)

    await orch._log_tool_call(
        requester_id=42,
        tool_name="assign_role",
        args={"user_id": "1", "role_id": "2"},
        result={"ok": True},
    )

    async with db.connect() as conn:
        async with conn.execute("SELECT * FROM audit_log") as cur:
            rows = await cur.fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert row[2] == "assign_role"          # tool_name
    assert row[4] == 42                      # requester_id
    assert json.loads(row[3])["user_id"] == "1"   # args
    assert json.loads(row[5]) == {"ok": True}     # result


async def test_log_tool_call_multiple_rows(tmp_db, monkeypatch):
    monkeypatch.setattr(orch, "GUILD_ID", 111)
    monkeypatch.setattr(db, "DB_PATH", tmp_db)

    await orch._log_tool_call(1, "assign_role", {}, {"ok": True})
    await orch._log_tool_call(2, "remove_role", {}, {"error": "oops"})

    async with db.connect() as conn:
        async with conn.execute("SELECT tool_name FROM audit_log ORDER BY id") as cur:
            names = [r[0] for r in await cur.fetchall()]

    assert names == ["assign_role", "remove_role"]


async def test_log_tool_call_denied_result(tmp_db, monkeypatch):
    monkeypatch.setattr(orch, "GUILD_ID", 111)
    monkeypatch.setattr(db, "DB_PATH", tmp_db)

    denied = {"denied": "Not on allowlist"}
    await orch._log_tool_call(99, "delete_role", {"role_id": "5"}, denied)

    async with db.connect() as conn:
        async with conn.execute("SELECT result FROM audit_log") as cur:
            row = await cur.fetchone()

    assert json.loads(row[0]) == denied


async def test_log_tool_call_cancelled_result(tmp_db, monkeypatch):
    monkeypatch.setattr(orch, "GUILD_ID", 111)
    monkeypatch.setattr(db, "DB_PATH", tmp_db)

    cancelled = {"cancelled": "The user cancelled this action."}
    await orch._log_tool_call(7, "create_role", {"name": "Test"}, cancelled)

    async with db.connect() as conn:
        async with conn.execute("SELECT result FROM audit_log") as cur:
            row = await cur.fetchone()

    assert json.loads(row[0]) == cancelled


# ---------------------------------------------------------------------------
# _run_loop — audit log rows for each outcome
#
# We patch the heavy dependencies (Gemini chat, Discord objects, tool dispatch,
# auth, confirmation) so these tests run without any network or Discord token.
# ---------------------------------------------------------------------------

def _make_function_call(name: str, args: dict):
    fc = MagicMock()
    fc.name = name
    fc.args = args
    return fc


def _make_response(function_calls=None, text=None):
    """Build a minimal fake Gemini response."""
    resp = MagicMock()
    resp.text = text or "done"
    part = MagicMock()
    if function_calls:
        part.function_call = function_calls[0]
        resp.candidates = [MagicMock(content=MagicMock(parts=[part]))]
    else:
        part.function_call = None
        resp.candidates = [MagicMock(content=MagicMock(parts=[part]))]
    return resp


def _make_multi_response(calls):
    """Build a response with multiple function_call parts."""
    resp = MagicMock()
    resp.text = "done"
    parts = []
    for fc in calls:
        p = MagicMock()
        p.function_call = fc
        parts.append(p)
    resp.candidates = [MagicMock(content=MagicMock(parts=parts))]
    return resp


async def _run(
    tmp_db,
    monkeypatch,
    *,
    function_calls,
    is_write: bool,
    auth_allowed: bool = True,
    confirmed: bool = True,
    dispatch_raises: Exception | None = None,
):
    """Helper: patch dependencies and call _run_loop, return audit_log rows."""
    monkeypatch.setattr(orch, "GUILD_ID", 111)
    monkeypatch.setattr(db, "DB_PATH", tmp_db)

    # Two-turn chat: first response has tool calls, second has the final text.
    final_resp = _make_response(text="all done")
    chat = AsyncMock()
    chat.send_message = AsyncMock(side_effect=[
        _make_multi_response(function_calls),
        final_resp,
    ])

    user = MagicMock()
    user.id = 42
    user.display_name = "Alice"
    # Make isinstance(user, discord.Member) return True so the auth branch
    # reaches auth.is_allowed() rather than short-circuiting to "denied".
    user.__class__ = discord.Member

    guild = MagicMock()
    guild.name = "TestGuild"
    guild.id = 111
    guild.text_channels = []
    guild.fetch_member = AsyncMock(return_value=user)

    status_msg = AsyncMock()
    status_msg.id = 99

    bot_client = AsyncMock()

    dispatch_mock = (
        AsyncMock(side_effect=dispatch_raises)
        if dispatch_raises
        else AsyncMock(return_value={"ok": True})
    )
    with (
        patch("bot.agent.orchestrator.is_write_call", return_value=is_write),
        patch("bot.agent.orchestrator.auth.is_allowed", AsyncMock(return_value=auth_allowed)),
        patch("bot.agent.orchestrator.confirmation.request_confirmation", AsyncMock(return_value=confirmed)),
        patch("bot.agent.orchestrator.describe_write_action", return_value="some diff"),
        patch("bot.agent.orchestrator.get_tool_label", return_value="label"),
        patch("bot.agent.orchestrator.dispatch", dispatch_mock),
        patch("bot.agent.orchestrator._save_turn", AsyncMock()),
    ):
        await orch._run_loop(chat, user, guild, 1, "hello", status_msg, bot_client)

    async with db.connect() as conn:
        async with conn.execute("SELECT tool_name, result FROM audit_log ORDER BY id") as cur:
            return await cur.fetchall()


async def test_audit_successful_tool(tmp_db, monkeypatch):
    fc = _make_function_call("search_messages", {"channel_id": "1", "query": "hi"})
    rows = await _run(tmp_db, monkeypatch, function_calls=[fc], is_write=False)

    assert len(rows) == 1
    assert rows[0][0] == "search_messages"
    result = json.loads(rows[0][1])
    assert result == {"ok": True}


async def test_audit_auth_denied(tmp_db, monkeypatch):
    fc = _make_function_call("assign_role", {"user_id": "1", "role_id": "2"})
    rows = await _run(
        tmp_db, monkeypatch,
        function_calls=[fc],
        is_write=True,
        auth_allowed=False,
    )

    assert len(rows) == 1
    assert rows[0][0] == "assign_role"
    result = json.loads(rows[0][1])
    assert "denied" in result


async def test_audit_user_cancelled(tmp_db, monkeypatch):
    fc = _make_function_call("delete_role", {"role_id": "5"})
    rows = await _run(
        tmp_db, monkeypatch,
        function_calls=[fc],
        is_write=True,
        auth_allowed=True,
        confirmed=False,
    )

    assert len(rows) == 1
    assert rows[0][0] == "delete_role"
    result = json.loads(rows[0][1])
    assert "cancelled" in result


async def test_audit_tool_exception(tmp_db, monkeypatch):
    fc = _make_function_call("set_channel_permission", {"channel_id": "1"})
    rows = await _run(
        tmp_db, monkeypatch,
        function_calls=[fc],
        is_write=False,
        dispatch_raises=RuntimeError("discord exploded"),
    )

    assert len(rows) == 1
    assert rows[0][0] == "set_channel_permission"
    result = json.loads(rows[0][1])
    assert "error" in result
    assert "discord exploded" in result["error"]


async def test_audit_multiple_write_calls_cancelled(tmp_db, monkeypatch):
    """When a batch of write calls is cancelled, every call in the batch is logged."""
    fc1 = _make_function_call("assign_role", {"user_id": "1", "role_id": "2"})
    fc2 = _make_function_call("assign_role", {"user_id": "3", "role_id": "4"})
    rows = await _run(
        tmp_db, monkeypatch,
        function_calls=[fc1, fc2],
        is_write=True,
        auth_allowed=True,
        confirmed=False,
    )

    assert len(rows) == 2
    for name, result_json in rows:
        assert name == "assign_role"
        assert "cancelled" in json.loads(result_json)
