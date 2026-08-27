"""Tests for get_bot_commands tool."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.tools.permissions import get_bot_commands


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_option(name, description="desc", option_type=None, required=False, choices=None, suboptions=None):
    opt = MagicMock()
    opt.name = name
    opt.description = description
    opt.type = MagicMock()
    opt.type.name = option_type or "STRING"
    opt.required = required
    opt.choices = choices or []
    opt.options = suboptions or []
    return opt


def _make_command(name, description="A command", app_id=100, options=None):
    cmd = MagicMock()
    cmd.name = name
    cmd.description = description
    cmd.application_id = app_id
    cmd.options = options or []
    return cmd


def _make_bot_member(name, bot_id):
    member = MagicMock()
    member.bot = True
    member.display_name = name
    member.id = bot_id
    return member


def _make_guild(members, commands):
    guild = MagicMock()
    guild.members = members
    guild.fetch_commands = AsyncMock(return_value=commands)
    return guild


# ---------------------------------------------------------------------------
# bot="all" — basic cases
# ---------------------------------------------------------------------------

async def test_all_returns_every_bot():
    members = [
        _make_bot_member("MEE6", 100),
        _make_bot_member("Carl-bot", 200),
    ]
    commands = [
        _make_command("ban", app_id=100),
        _make_command("rank", app_id=100),
        _make_command("prefix", app_id=200),
    ]
    guild = _make_guild(members, commands)

    result = await get_bot_commands(guild, bot="all")

    assert result["total_commands"] == 3
    assert result["bot_count"] == 2
    bots_by_name = {b["bot"]: b for b in result["bots"]}
    assert bots_by_name["MEE6"]["command_count"] == 2
    assert bots_by_name["Carl-bot"]["command_count"] == 1


async def test_all_commands_sorted_alphabetically():
    members = [_make_bot_member("MEE6", 100)]
    commands = [
        _make_command("rank", app_id=100),
        _make_command("ban", app_id=100),
        _make_command("levels", app_id=100),
    ]
    guild = _make_guild(members, commands)

    result = await get_bot_commands(guild, bot="all")
    names = [c["name"] for c in result["bots"][0]["commands"]]
    assert names == sorted(names)


async def test_all_no_commands_registered():
    members = [_make_bot_member("SilentBot", 100)]
    guild = _make_guild(members, [])

    result = await get_bot_commands(guild, bot="all")

    assert result["total_commands"] == 0
    assert result["bot_count"] == 0
    assert result["bots"] == []


async def test_all_no_bots_in_server():
    human = MagicMock()
    human.bot = False
    guild = _make_guild([human], [])

    result = await get_bot_commands(guild, bot="all")

    assert result["total_commands"] == 0
    assert result["bot_count"] == 0


async def test_all_unknown_bot_application_id():
    """Commands whose app_id has no matching guild member still appear."""
    guild = _make_guild([], [_make_command("ping", app_id=999)])

    result = await get_bot_commands(guild, bot="all")

    assert result["total_commands"] == 1
    assert "unknown bot" in result["bots"][0]["bot"]


# ---------------------------------------------------------------------------
# bot=<name> — filtering by display name
# ---------------------------------------------------------------------------

async def test_filter_by_name_exact():
    members = [
        _make_bot_member("MEE6", 100),
        _make_bot_member("Carl-bot", 200),
    ]
    commands = [
        _make_command("ban", app_id=100),
        _make_command("prefix", app_id=200),
    ]
    guild = _make_guild(members, commands)

    result = await get_bot_commands(guild, bot="MEE6")

    assert result["bot"] == "MEE6"
    assert result["command_count"] == 1
    assert result["commands"][0]["name"] == "ban"


async def test_filter_by_name_case_insensitive_substring():
    members = [_make_bot_member("Carl-bot", 200)]
    commands = [_make_command("prefix", app_id=200)]
    guild = _make_guild(members, commands)

    result = await get_bot_commands(guild, bot="carl")

    assert result["bot"] == "Carl-bot"
    assert result["command_count"] == 1


async def test_filter_by_name_not_found():
    members = [_make_bot_member("MEE6", 100)]
    guild = _make_guild(members, [])

    result = await get_bot_commands(guild, bot="NonExistentBot")

    assert "error" in result
    assert "NonExistentBot" in result["error"]


# ---------------------------------------------------------------------------
# bot=<id> — filtering by numeric user ID
# ---------------------------------------------------------------------------

async def test_filter_by_id():
    members = [
        _make_bot_member("MEE6", 100),
        _make_bot_member("Carl-bot", 200),
    ]
    commands = [
        _make_command("ban", app_id=100),
        _make_command("prefix", app_id=200),
    ]
    guild = _make_guild(members, commands)

    result = await get_bot_commands(guild, bot="200")

    assert result["bot"] == "Carl-bot"
    assert result["bot_id"] == "200"
    assert result["commands"][0]["name"] == "prefix"


async def test_filter_by_id_no_commands():
    members = [_make_bot_member("QuietBot", 300)]
    guild = _make_guild(members, [])

    result = await get_bot_commands(guild, bot="300")

    assert result["command_count"] == 0
    assert result["commands"] == []
    assert "note" in result


# ---------------------------------------------------------------------------
# Command structure — options, subcommands, choices
# ---------------------------------------------------------------------------

async def test_command_options_included():
    opt = _make_option("user", description="Target user", option_type="USER", required=True)
    cmd = _make_command("kick", app_id=100, options=[opt])
    members = [_make_bot_member("ModBot", 100)]
    guild = _make_guild(members, [cmd])

    result = await get_bot_commands(guild, bot="all")

    command = result["bots"][0]["commands"][0]
    assert command["name"] == "kick"
    assert len(command["options"]) == 1
    assert command["options"][0]["name"] == "user"
    assert command["options"][0]["required"] is True
    assert command["options"][0]["type"] == "USER"


async def test_command_choices_included():
    choice_a = MagicMock()
    choice_a.name = "soft"
    choice_b = MagicMock()
    choice_b.name = "hard"
    opt = _make_option("ban_type", choices=[choice_a, choice_b])
    cmd = _make_command("ban", app_id=100, options=[opt])
    members = [_make_bot_member("ModBot", 100)]
    guild = _make_guild(members, [cmd])

    result = await get_bot_commands(guild, bot="all")

    option = result["bots"][0]["commands"][0]["options"][0]
    assert "soft" in option["choices"]
    assert "hard" in option["choices"]


async def test_command_nested_subcommands():
    subopt = _make_option("channel", option_type="CHANNEL", required=False)
    subcmd = _make_option("logs", option_type="SUB_COMMAND", suboptions=[subopt])
    cmd = _make_command("config", app_id=100, options=[subcmd])
    members = [_make_bot_member("AdminBot", 100)]
    guild = _make_guild(members, [cmd])

    result = await get_bot_commands(guild, bot="all")

    top_option = result["bots"][0]["commands"][0]["options"][0]
    assert top_option["name"] == "logs"
    assert top_option["options"][0]["name"] == "channel"


async def test_command_no_options_omitted():
    cmd = _make_command("ping", app_id=100, options=[])
    members = [_make_bot_member("UtilBot", 100)]
    guild = _make_guild(members, [cmd])

    result = await get_bot_commands(guild, bot="all")

    command = result["bots"][0]["commands"][0]
    assert "options" not in command


# ---------------------------------------------------------------------------
# Output shape guarantees
# ---------------------------------------------------------------------------

async def test_bot_id_is_string():
    members = [_make_bot_member("MEE6", 100)]
    commands = [_make_command("ban", app_id=100)]
    guild = _make_guild(members, commands)

    result = await get_bot_commands(guild, bot="all")

    assert isinstance(result["bots"][0]["bot_id"], str)


async def test_single_bot_result_shape():
    members = [_make_bot_member("MEE6", 100)]
    commands = [_make_command("ban", app_id=100)]
    guild = _make_guild(members, commands)

    result = await get_bot_commands(guild, bot="MEE6")

    assert "bot" in result
    assert "bot_id" in result
    assert "command_count" in result
    assert "commands" in result
