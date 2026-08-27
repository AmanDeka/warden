"""Tests for orchestrator helper functions."""

from unittest.mock import MagicMock

from bot.agent.orchestrator import _build_context, _strip_mention


# ---------------------------------------------------------------------------
# _strip_mention
# ---------------------------------------------------------------------------

def test_strip_mention_at():
    assert _strip_mention("<@123> hello", 123) == "hello"


def test_strip_mention_at_bang():
    assert _strip_mention("<@!123> hello", 123) == "hello"


def test_strip_mention_both():
    assert _strip_mention("<@123> <@!123> text", 123) == "text"


def test_strip_mention_no_mention():
    assert _strip_mention("just text", 123) == "just text"


def test_strip_mention_different_bot_id():
    # Different bot id — mention not stripped
    result = _strip_mention("<@456> hello", 123)
    assert "<@456>" in result


def test_strip_mention_trailing_whitespace():
    assert _strip_mention("  <@123>  hi  ", 123) == "hi"


# ---------------------------------------------------------------------------
# _build_context
# ---------------------------------------------------------------------------

def _make_channel(name, readable=True):
    ch = MagicMock()
    ch.name = name
    ch.id = hash(name) % 10**15

    me_perms = MagicMock()
    me_perms.read_messages = readable
    ch.permissions_for.return_value = me_perms
    return ch


def test_build_context_with_guild():
    guild = MagicMock()
    guild.name = "TestServer"
    guild.id = 111
    guild.text_channels = [
        _make_channel("general", readable=True),
        _make_channel("secret", readable=False),
    ]

    user = MagicMock()
    user.display_name = "Alice"
    user.id = 42

    ctx = _build_context(guild, user)

    assert "TestServer" in ctx
    assert "Alice" in ctx
    assert "#general" in ctx
    assert "#secret" not in ctx


def test_build_context_no_guild():
    user = MagicMock()
    user.display_name = "Bob"
    user.id = 99

    ctx = _build_context(None, user)

    assert "Bob" in ctx
    assert "Guild:" not in ctx


def test_build_context_contains_user_id():
    guild = MagicMock()
    guild.name = "Server"
    guild.id = 1
    guild.text_channels = []

    user = MagicMock()
    user.display_name = "Carol"
    user.id = 55555

    ctx = _build_context(guild, user)
    assert "55555" in ctx
