"""Tests for describe_write_action in tool_schemas."""

from unittest.mock import MagicMock

from bot.agent.tool_schemas import describe_write_action


def _make_guild(role_name="Mods", member_name="Dave", channel_name="general"):
    role = MagicMock()
    role.name = role_name

    member = MagicMock()
    member.display_name = member_name

    channel = MagicMock()
    channel.name = channel_name

    guild = MagicMock()
    guild.get_role.return_value = role
    guild.get_member.return_value = member
    guild.get_channel.return_value = channel
    return guild


# ---------------------------------------------------------------------------
# assign_role / remove_role
# ---------------------------------------------------------------------------

def test_describe_assign_role():
    guild = _make_guild(role_name="Mods", member_name="Alice")
    result = describe_write_action("manage_roles", {"action": "assign", "role_id": "1", "user_id": "2"}, guild)
    assert "Mods" in result
    assert "Alice" in result
    assert "Assign" in result


def test_describe_remove_role():
    guild = _make_guild(role_name="Mods", member_name="Alice")
    result = describe_write_action("manage_roles", {"action": "remove", "role_id": "1", "user_id": "2"}, guild)
    assert "Remove" in result
    assert "Mods" in result
    assert "Alice" in result


# ---------------------------------------------------------------------------
# set_channel_permission
# ---------------------------------------------------------------------------

def test_describe_set_channel_permission():
    guild = _make_guild(channel_name="staff")
    result = describe_write_action(
        "set_channel_permission",
        {"channel_id": "10", "target_id": "20", "allow": ["view_channel"], "deny": ["send_messages"]},
        guild,
    )
    assert "staff" in result
    assert "view_channel" in result
    assert "send_messages" in result


def test_describe_set_channel_permission_empty_lists():
    guild = _make_guild()
    result = describe_write_action(
        "set_channel_permission",
        {"channel_id": "10", "target_id": "20"},
        guild,
    )
    assert "none" in result


# ---------------------------------------------------------------------------
# create_role / delete_role
# ---------------------------------------------------------------------------

def test_describe_create_role():
    result = describe_write_action(
        "manage_roles",
        {"action": "create", "name": "NewRole", "permissions": ["send_messages", "view_channel"]},
        None,
    )
    assert "NewRole" in result
    assert "send_messages" in result


def test_describe_create_role_no_permissions():
    result = describe_write_action("manage_roles", {"action": "create", "name": "Empty"}, None)
    assert "Empty" in result
    assert "none" in result


def test_describe_delete_role():
    guild = _make_guild(role_name="OldRole")
    result = describe_write_action("manage_roles", {"action": "delete", "role_id": "5"}, guild)
    assert "OldRole" in result


# ---------------------------------------------------------------------------
# Fallback / edge cases
# ---------------------------------------------------------------------------

def test_describe_unknown_tool():
    result = describe_write_action("nonexistent_tool", {"foo": "bar"}, None)
    assert "nonexistent_tool" in result


def test_describe_missing_ids_no_guild():
    result = describe_write_action("assign_role", {"role_id": "99", "user_id": "88"}, None)
    assert "99" in result or "88" in result


def test_describe_missing_ids_guild_none_match():
    guild = MagicMock()
    guild.get_role.return_value = None
    guild.get_member.return_value = None
    guild.get_channel.return_value = None
    result = describe_write_action("assign_role", {"role_id": "99", "user_id": "88"}, guild)
    # Falls back to raw id strings — should not raise
    assert isinstance(result, str)
