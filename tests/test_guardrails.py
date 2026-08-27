"""Tests for guardrail auth functions."""

from unittest.mock import MagicMock

import pytest

from bot.guardrails.auth import is_allowed, remove_from_allowlist
from bot.storage import db


# ---------------------------------------------------------------------------
# is_allowed
# ---------------------------------------------------------------------------

async def test_is_allowed_true(tmp_db):
    role_id = 42
    await db.add_allowlist_role(role_id, guild_id=111, added_by=1)

    role = MagicMock()
    role.id = role_id

    member = MagicMock()
    member.roles = [role]

    assert await is_allowed(member) is True


async def test_is_allowed_false_empty_allowlist(tmp_db):
    role = MagicMock()
    role.id = 99

    member = MagicMock()
    member.roles = [role]

    assert await is_allowed(member) is False


async def test_is_allowed_role_not_on_list(tmp_db):
    await db.add_allowlist_role(100, guild_id=111, added_by=1)

    role = MagicMock()
    role.id = 200  # different from allowlisted 100

    member = MagicMock()
    member.roles = [role]

    assert await is_allowed(member) is False


async def test_is_allowed_one_of_many_roles(tmp_db):
    await db.add_allowlist_role(55, guild_id=111, added_by=1)

    role_a = MagicMock()
    role_a.id = 11
    role_b = MagicMock()
    role_b.id = 55

    member = MagicMock()
    member.roles = [role_a, role_b]

    assert await is_allowed(member) is True


# ---------------------------------------------------------------------------
# remove_from_allowlist
# ---------------------------------------------------------------------------

async def test_remove_from_allowlist_success(tmp_db):
    role_id = 77
    await db.add_allowlist_role(role_id, guild_id=111, added_by=1)

    role = MagicMock()
    role.id = role_id

    result = await remove_from_allowlist(role)
    assert result is True

    ids = await db.get_allowlist_role_ids()
    assert role_id not in ids


async def test_remove_from_allowlist_not_listed(tmp_db):
    role = MagicMock()
    role.id = 9999

    result = await remove_from_allowlist(role)
    assert result is False
