"""Tests for permission and role tools."""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.tools.permissions import (
    _overwrite_to_dict,
    _permission_names,
    assign_role,
    get_member_roles,
    get_role_members,
    list_permissions,
    list_roles,
    remove_role,
    scan_bots,
)


# ---------------------------------------------------------------------------
# _permission_names
# ---------------------------------------------------------------------------

def test_permission_names_basic():
    perms = discord.Permissions(send_messages=True, view_channel=True)
    names = _permission_names(perms)
    assert "send_messages" in names
    # discord.py 2.x iterates view_channel as read_messages internally
    assert "read_messages" in names


def test_permission_names_empty():
    assert _permission_names(discord.Permissions.none()) == []


def test_permission_names_single():
    perms = discord.Permissions(administrator=True)
    names = _permission_names(perms)
    assert "administrator" in names


# ---------------------------------------------------------------------------
# _overwrite_to_dict
# ---------------------------------------------------------------------------

def test_overwrite_to_dict_role():
    target = MagicMock()
    target.__class__ = discord.Role
    target.name = "Mods"
    target.id = 1
    ow = discord.PermissionOverwrite(send_messages=True, view_channel=False)
    result = _overwrite_to_dict(target, ow)
    assert result["target_type"] == "role"
    assert result["target_name"] == "Mods"
    assert "send_messages" in result["allow"]
    # view_channel is aliased to read_messages in discord.py 2.x iteration
    assert "read_messages" in result["deny"]


def test_overwrite_to_dict_member():
    target = MagicMock()
    target.__class__ = discord.Member
    target.display_name = "Alice"
    target.id = 2
    ow = discord.PermissionOverwrite()
    result = _overwrite_to_dict(target, ow)
    assert result["target_type"] == "member"
    assert result["target_name"] == "Alice"


def test_overwrite_to_dict_unknown():
    target = MagicMock(spec=object)
    target.id = 99
    ow = discord.PermissionOverwrite()
    result = _overwrite_to_dict(target, ow)
    assert result["target_type"] == "unknown"
    assert "99" in result["target_name"]


# ---------------------------------------------------------------------------
# list_permissions
# ---------------------------------------------------------------------------

def _make_guild_channel(name="general", channel_id=10):
    ch = MagicMock()
    ch.__class__ = discord.TextChannel
    ch.name = name
    ch.id = channel_id
    ch.category = None
    ch.permissions_synced = True
    ch.overwrites = {}
    return ch


async def test_list_permissions_channel():
    guild = MagicMock()
    ch = _make_guild_channel()
    guild.get_channel.return_value = ch
    result = await list_permissions(guild, 10)
    assert result["type"] == "channel"
    assert result["name"] == "general"


async def test_list_permissions_role():
    guild = MagicMock()
    guild.get_channel.return_value = None
    role = MagicMock()
    role.name = "Admin"
    role.id = 5
    role.color = discord.Color.default()
    role.hoist = False
    role.mentionable = True
    role.position = 3
    role.permissions = discord.Permissions(administrator=True)
    guild.get_role.return_value = role
    result = await list_permissions(guild, 5)
    assert result["type"] == "role"
    assert result["name"] == "Admin"
    assert "administrator" in result["permissions"]


async def test_list_permissions_not_found():
    guild = MagicMock()
    guild.get_channel.return_value = None
    guild.get_role.return_value = None
    result = await list_permissions(guild, 999)
    assert "error" in result


# ---------------------------------------------------------------------------
# list_roles
# ---------------------------------------------------------------------------

async def test_list_roles():
    role_a = MagicMock()
    role_a.name = "Admin"
    role_a.id = 1
    role_a.color = discord.Color.red()
    role_a.hoist = True
    role_a.mentionable = False
    role_a.position = 10
    role_a.managed = False
    role_a.permissions = discord.Permissions(administrator=True)
    role_a.members = [MagicMock(), MagicMock()]

    role_b = MagicMock()
    role_b.name = "Member"
    role_b.id = 2
    role_b.color = discord.Color.default()
    role_b.hoist = False
    role_b.mentionable = True
    role_b.position = 1
    role_b.managed = False
    role_b.permissions = discord.Permissions.none()
    role_b.members = [MagicMock()]

    guild = MagicMock()
    guild.roles = [role_b, role_a]

    result = await list_roles(guild)
    assert result[0]["name"] == "Admin"
    assert result[0]["member_count"] == 2
    assert result[1]["name"] == "Member"


# ---------------------------------------------------------------------------
# get_member_roles
# ---------------------------------------------------------------------------

async def test_get_member_roles_found():
    role = MagicMock()
    role.name = "Mod"
    role.id = 7
    role.position = 5
    role.is_default.return_value = False

    member = MagicMock()
    member.display_name = "Bob"
    member.id = 42
    member.roles = [role]

    guild = MagicMock()
    guild.get_member.return_value = member

    result = await get_member_roles(guild, 42)
    assert result["user"] == "Bob"
    assert len(result["roles"]) == 1
    assert result["roles"][0]["name"] == "Mod"


async def test_get_member_roles_not_found():
    guild = MagicMock()
    guild.get_member.return_value = None
    response_mock = MagicMock()
    response_mock.status = 404
    guild.fetch_member = AsyncMock(side_effect=discord.NotFound(response_mock, "not found"))
    result = await get_member_roles(guild, 999)
    assert "error" in result


# ---------------------------------------------------------------------------
# scan_bots
# ---------------------------------------------------------------------------

def _make_bot_member(name, dangerous=False):
    member = MagicMock()
    member.bot = True
    member.display_name = name
    member.id = abs(hash(name)) % 10**15
    member.joined_at = None
    member.roles = []
    member.guild_permissions = (
        discord.Permissions(administrator=True) if dangerous else discord.Permissions.none()
    )
    return member


async def test_scan_bots_with_dangerous_perms():
    guild = MagicMock()
    guild.members = [_make_bot_member("EvilBot", dangerous=True)]
    result = await scan_bots(guild)
    assert result["bot_count"] == 1
    assert len(result["flagged"]) == 1
    assert "administrator" in result["flagged"][0]["dangerous_permissions"]


async def test_scan_bots_clean():
    guild = MagicMock()
    guild.members = [_make_bot_member("GoodBot", dangerous=False)]
    result = await scan_bots(guild)
    assert result["bot_count"] == 1
    assert result["flagged"] == []


async def test_scan_bots_no_bots():
    human = MagicMock()
    human.bot = False
    guild = MagicMock()
    guild.members = [human]
    result = await scan_bots(guild)
    assert result["bot_count"] == 0
    assert result["bots"] == []


async def test_scan_bots_mixed():
    guild = MagicMock()
    guild.members = [
        _make_bot_member("CleanBot", dangerous=False),
        _make_bot_member("BadBot", dangerous=True),
    ]
    result = await scan_bots(guild)
    assert result["bot_count"] == 2
    assert len(result["flagged"]) == 1
    assert result["flagged"][0]["name"] == "BadBot"


# ---------------------------------------------------------------------------
# assign_role
# ---------------------------------------------------------------------------

def _make_guild_with_member_and_role(member_has_role=False):
    role = MagicMock()
    role.name = "Tester"
    role.id = 55

    member = MagicMock()
    member.display_name = "Dave"
    member.id = 77
    member.roles = [role] if member_has_role else []
    member.add_roles = AsyncMock()

    guild = MagicMock()
    guild.get_member.return_value = member
    guild.get_role.return_value = role
    return guild, member, role


async def test_assign_role_success():
    guild, member, role = _make_guild_with_member_and_role(member_has_role=False)
    result = await assign_role(guild, member.id, role.id)
    assert "ok" in result
    member.add_roles.assert_called_once_with(role, reason="Warden: assign_role tool")


async def test_assign_role_already_has():
    guild, member, role = _make_guild_with_member_and_role(member_has_role=True)
    result = await assign_role(guild, member.id, role.id)
    assert "info" in result
    member.add_roles.assert_not_called()


async def test_assign_role_member_not_found():
    guild = MagicMock()
    guild.get_member.return_value = None
    response_mock = MagicMock()
    response_mock.status = 404
    guild.fetch_member = AsyncMock(side_effect=discord.NotFound(response_mock, "not found"))
    result = await assign_role(guild, 999, 1)
    assert "error" in result


async def test_assign_role_forbidden():
    guild, member, role = _make_guild_with_member_and_role(member_has_role=False)
    member.add_roles = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "forbidden"))
    result = await assign_role(guild, member.id, role.id)
    assert "error" in result


# ---------------------------------------------------------------------------
# remove_role
# ---------------------------------------------------------------------------

async def test_remove_role_success():
    guild, member, role = _make_guild_with_member_and_role(member_has_role=True)
    member.remove_roles = AsyncMock()
    result = await remove_role(guild, member.id, role.id)
    assert "ok" in result
    member.remove_roles.assert_called_once_with(role, reason="Warden: remove_role tool")


async def test_remove_role_not_have():
    guild, member, role = _make_guild_with_member_and_role(member_has_role=False)
    result = await remove_role(guild, member.id, role.id)
    assert "info" in result


async def test_remove_role_forbidden():
    guild, member, role = _make_guild_with_member_and_role(member_has_role=True)
    member.remove_roles = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "forbidden"))
    result = await remove_role(guild, member.id, role.id)
    assert "error" in result


# ---------------------------------------------------------------------------
# get_role_members
# ---------------------------------------------------------------------------

def _make_role_member(name: str, user_id: int):
    m = MagicMock()
    m.display_name = name
    m.id = user_id
    m.joined_at = None
    return m


async def test_get_role_members_found():
    member_a = _make_role_member("Alice", 1)
    member_b = _make_role_member("Bob", 2)

    role = MagicMock()
    role.name = "Moderator"
    role.id = 10
    role.members = [member_b, member_a]  # unsorted intentionally

    guild = MagicMock()
    guild.get_role.return_value = role

    result = await get_role_members(guild, 10)
    assert result["role"] == "Moderator"
    assert result["member_count"] == 2
    # sorted alphabetically
    assert result["members"][0]["name"] == "Alice"
    assert result["members"][1]["name"] == "Bob"


async def test_get_role_members_empty():
    role = MagicMock()
    role.name = "EmptyRole"
    role.id = 20
    role.members = []

    guild = MagicMock()
    guild.get_role.return_value = role

    result = await get_role_members(guild, 20)
    assert result["member_count"] == 0
    assert result["members"] == []


async def test_get_role_members_not_found():
    guild = MagicMock()
    guild.get_role.return_value = None
    result = await get_role_members(guild, 999)
    assert "error" in result


# ---------------------------------------------------------------------------
# is_write_call / get_tool_label (schema helpers)
# ---------------------------------------------------------------------------

from bot.agent.tool_schemas import get_tool_label, is_write_call


def test_is_write_call_manage_roles_write_actions():
    for action in ("assign", "remove", "create", "delete"):
        assert is_write_call("manage_roles", {"action": action})


def test_is_write_call_manage_roles_read_actions():
    for action in ("list", "get_member_roles", "get_role_members"):
        assert not is_write_call("manage_roles", {"action": action})


def test_is_write_call_other_write_tools():
    assert is_write_call("set_channel_permission", {})
    assert is_write_call("manage_server", {"action": "kick"})


def test_is_write_call_read_tools():
    assert not is_write_call("list_permissions", {})
    assert not is_write_call("get_audit_log", {})


def test_get_tool_label_manage_roles():
    assert get_tool_label("manage_roles", {"action": "assign"}) == "Assigning role"
    assert get_tool_label("manage_roles", {"action": "list"}) == "Listing roles"
    assert get_tool_label("manage_roles", {"action": "get_role_members"}) == "Getting role members"


def test_get_tool_label_fallback():
    assert get_tool_label("list_permissions", {}) == "Checking permissions"
    assert get_tool_label("unknown_tool", {}) == "unknown_tool"
