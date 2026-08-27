"""Unit tests for bot/tools/moderation.py and allowlist enforcement."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from bot.guardrails.auth import is_allowed
from bot.storage import db
from bot.tools.moderation import manage_server
from bot.agent.tool_schemas import WRITE_TOOLS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _guild(members=None, channels=None):
    guild = MagicMock(spec=discord.Guild)
    guild.get_member = MagicMock(return_value=None)
    guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "not found"))
    guild.get_channel = MagicMock(return_value=None)
    guild.ban = AsyncMock()
    guild.unban = AsyncMock()
    guild.fetch_ban = AsyncMock()
    guild.create_text_channel = AsyncMock()
    guild.create_voice_channel = AsyncMock()
    guild.create_forum = AsyncMock()
    return guild


def _member(display_name="TestUser", *, timed_out=False):
    m = MagicMock(spec=discord.Member)
    m.display_name = display_name
    m.kick = AsyncMock()
    m.timeout = AsyncMock()
    m.move_to = AsyncMock()
    m.is_timed_out = MagicMock(return_value=timed_out)
    m.voice = None
    return m


def _channel(name="general"):
    ch = MagicMock(spec=discord.TextChannel)
    ch.__class__ = discord.abc.GuildChannel
    ch.name = name
    ch.delete = AsyncMock()
    ch.edit = AsyncMock()
    return ch


# ---------------------------------------------------------------------------
# manage_server is a write tool
# ---------------------------------------------------------------------------

def test_manage_server_in_write_tools():
    assert "manage_server" in WRITE_TOOLS


# ---------------------------------------------------------------------------
# kick
# ---------------------------------------------------------------------------

async def test_kick_success():
    guild = _guild()
    member = _member("Alice")
    guild.get_member = MagicMock(return_value=member)

    result = await manage_server(guild, action="kick", user_id=123, reason="spamming")

    member.kick.assert_called_once()
    assert "ok" in result
    assert "Alice" in result["ok"]


async def test_kick_missing_user_id():
    result = await manage_server(_guild(), action="kick")
    assert "error" in result
    assert "user_id" in result["error"]


async def test_kick_member_not_found():
    guild = _guild()
    result = await manage_server(guild, action="kick", user_id=999)
    assert "error" in result
    assert "not found" in result["error"].lower()


async def test_kick_forbidden():
    guild = _guild()
    member = _member()
    member.kick = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "forbidden"))
    guild.get_member = MagicMock(return_value=member)

    result = await manage_server(guild, action="kick", user_id=1)
    assert "error" in result
    assert "permission" in result["error"].lower()


# ---------------------------------------------------------------------------
# ban
# ---------------------------------------------------------------------------

async def test_ban_success():
    guild = _guild()
    member = _member("Bob")
    guild.get_member = MagicMock(return_value=member)

    result = await manage_server(guild, action="ban", user_id=1, delete_message_days=1)

    guild.ban.assert_called_once()
    assert "ok" in result
    assert "Bob" in result["ok"]


async def test_ban_clamps_delete_days():
    guild = _guild()
    member = _member()
    guild.get_member = MagicMock(return_value=member)

    await manage_server(guild, action="ban", user_id=1, delete_message_days=99)

    _, kwargs = guild.ban.call_args
    assert kwargs["delete_message_days"] <= 7


async def test_ban_missing_user_id():
    result = await manage_server(_guild(), action="ban")
    assert "error" in result


async def test_ban_forbidden():
    guild = _guild()
    guild.get_member = MagicMock(return_value=_member())
    guild.ban = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "forbidden"))

    result = await manage_server(guild, action="ban", user_id=1)
    assert "error" in result
    assert "permission" in result["error"].lower()


# ---------------------------------------------------------------------------
# unban
# ---------------------------------------------------------------------------

async def test_unban_success():
    guild = _guild()
    fake_user = MagicMock()
    fake_user.user = MagicMock()
    guild.fetch_ban = AsyncMock(return_value=fake_user)

    result = await manage_server(guild, action="unban", user_id=1)

    guild.unban.assert_called_once()
    assert "ok" in result


async def test_unban_not_banned():
    guild = _guild()
    guild.fetch_ban = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "not found"))

    result = await manage_server(guild, action="unban", user_id=1)
    assert "error" in result
    assert "ban" in result["error"].lower()


async def test_unban_missing_user_id():
    result = await manage_server(_guild(), action="unban")
    assert "error" in result


# ---------------------------------------------------------------------------
# timeout
# ---------------------------------------------------------------------------

async def test_timeout_success():
    guild = _guild()
    member = _member("Dave")
    guild.get_member = MagicMock(return_value=member)

    result = await manage_server(guild, action="timeout", user_id=1, duration_minutes=30)

    member.timeout.assert_called_once()
    assert "ok" in result
    assert "30" in result["ok"]


async def test_timeout_missing_duration():
    guild = _guild()
    guild.get_member = MagicMock(return_value=_member())

    result = await manage_server(guild, action="timeout", user_id=1)
    assert "error" in result
    assert "duration" in result["error"].lower()


async def test_timeout_zero_duration():
    guild = _guild()
    guild.get_member = MagicMock(return_value=_member())

    result = await manage_server(guild, action="timeout", user_id=1, duration_minutes=0)
    assert "error" in result


async def test_timeout_member_not_found():
    result = await manage_server(_guild(), action="timeout", user_id=999, duration_minutes=10)
    assert "error" in result
    assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# remove_timeout
# ---------------------------------------------------------------------------

async def test_remove_timeout_success():
    guild = _guild()
    member = _member(timed_out=True)
    guild.get_member = MagicMock(return_value=member)

    result = await manage_server(guild, action="remove_timeout", user_id=1)

    member.timeout.assert_called_once_with(None, reason="Warden")
    assert "ok" in result


async def test_remove_timeout_not_timed_out():
    guild = _guild()
    member = _member(timed_out=False)
    guild.get_member = MagicMock(return_value=member)

    result = await manage_server(guild, action="remove_timeout", user_id=1)
    assert "info" in result


async def test_remove_timeout_missing_user_id():
    result = await manage_server(_guild(), action="remove_timeout")
    assert "error" in result


# ---------------------------------------------------------------------------
# create_channel
# ---------------------------------------------------------------------------

async def test_create_text_channel_success():
    guild = _guild()
    created = MagicMock()
    created.name = "dev-chat"
    created.id = 555
    guild.create_text_channel = AsyncMock(return_value=created)

    result = await manage_server(guild, action="create_channel", new_name="dev-chat")

    guild.create_text_channel.assert_called_once()
    assert "ok" in result
    assert "dev-chat" in result["ok"]


async def test_create_voice_channel():
    guild = _guild()
    created = MagicMock()
    created.name = "Gaming"
    created.id = 666
    guild.create_voice_channel = AsyncMock(return_value=created)

    result = await manage_server(guild, action="create_channel", new_name="Gaming", channel_type="voice")

    guild.create_voice_channel.assert_called_once()
    assert "ok" in result


async def test_create_channel_missing_name():
    result = await manage_server(_guild(), action="create_channel")
    assert "error" in result


async def test_create_channel_forbidden():
    guild = _guild()
    guild.create_text_channel = AsyncMock(
        side_effect=discord.Forbidden(MagicMock(status=403), "forbidden")
    )

    result = await manage_server(guild, action="create_channel", new_name="test")
    assert "error" in result
    assert "permission" in result["error"].lower()


# ---------------------------------------------------------------------------
# delete_channel
# ---------------------------------------------------------------------------

async def test_delete_channel_success():
    guild = _guild()
    channel = _channel("old-channel")
    guild.get_channel = MagicMock(return_value=channel)

    result = await manage_server(guild, action="delete_channel", channel_id=1)

    channel.delete.assert_called_once()
    assert "ok" in result
    assert "old-channel" in result["ok"]


async def test_delete_channel_not_found():
    result = await manage_server(_guild(), action="delete_channel", channel_id=999)
    assert "error" in result
    assert "not found" in result["error"].lower()


async def test_delete_channel_missing_id():
    result = await manage_server(_guild(), action="delete_channel")
    assert "error" in result


# ---------------------------------------------------------------------------
# rename_channel
# ---------------------------------------------------------------------------

async def test_rename_channel_success():
    guild = _guild()
    channel = _channel("old-name")
    guild.get_channel = MagicMock(return_value=channel)

    result = await manage_server(guild, action="rename_channel", channel_id=1, new_name="new-name")

    channel.edit.assert_called_once()
    assert "ok" in result
    assert "new-name" in result["ok"]


async def test_rename_channel_missing_args():
    result = await manage_server(_guild(), action="rename_channel", channel_id=1)
    assert "error" in result


async def test_rename_channel_not_found():
    result = await manage_server(_guild(), action="rename_channel", channel_id=999, new_name="x")
    assert "error" in result


# ---------------------------------------------------------------------------
# move_member
# ---------------------------------------------------------------------------

async def test_move_member_success():
    guild = _guild()
    member = _member("Eve")
    member.voice = MagicMock()  # currently in a voice channel
    guild.get_member = MagicMock(return_value=member)

    vc = MagicMock(spec=discord.VoiceChannel)
    vc.name = "Gaming"
    guild.get_channel = MagicMock(return_value=vc)

    result = await manage_server(guild, action="move_member", user_id=1, voice_channel_id=2)

    member.move_to.assert_called_once_with(vc, reason="Warden")
    assert "ok" in result


async def test_move_member_not_in_voice():
    guild = _guild()
    member = _member()
    member.voice = None
    guild.get_member = MagicMock(return_value=member)

    vc = MagicMock(spec=discord.VoiceChannel)
    guild.get_channel = MagicMock(return_value=vc)

    result = await manage_server(guild, action="move_member", user_id=1, voice_channel_id=2)
    assert "error" in result
    assert "voice channel" in result["error"].lower()


async def test_move_member_missing_args():
    result = await manage_server(_guild(), action="move_member", user_id=1)
    assert "error" in result


# ---------------------------------------------------------------------------
# Unknown action
# ---------------------------------------------------------------------------

async def test_unknown_action():
    result = await manage_server(_guild(), action="explode")
    assert "error" in result
    assert "unknown" in result["error"].lower()


# ---------------------------------------------------------------------------
# Allowlist enforcement (integration with auth)
# ---------------------------------------------------------------------------

async def test_manage_server_blocked_without_allowlist_role(tmp_db):
    """A member with no allowlisted role must not pass the auth check."""
    role = MagicMock()
    role.id = 100

    member = MagicMock()
    member.roles = [role]

    assert await is_allowed(member) is False


async def test_manage_server_allowed_with_allowlist_role(tmp_db):
    """A member whose role is on the allowlist passes the auth check."""
    role_id = 200
    await db.add_allowlist_role(role_id, guild_id=111, added_by=1)

    role = MagicMock()
    role.id = role_id

    member = MagicMock()
    member.roles = [role]

    assert await is_allowed(member) is True


async def test_allowlist_removal_blocks_access(tmp_db):
    """Removing a role from the allowlist immediately revokes access."""
    from bot.guardrails.auth import remove_from_allowlist

    role_id = 300
    await db.add_allowlist_role(role_id, guild_id=111, added_by=1)

    role = MagicMock()
    role.id = role_id

    member = MagicMock()
    member.roles = [role]

    assert await is_allowed(member) is True

    await remove_from_allowlist(role)
    db._invalidate_allowlist_cache()

    assert await is_allowed(member) is False
