"""Tests for slash command Discord-level permission configuration."""

import discord

from bot.main import allowlist_group


def test_allowlist_group_requires_administrator():
    perms = allowlist_group.default_permissions
    assert perms is not None, "allowlist_group must have default_permissions set"
    assert perms.administrator, "allowlist_group must require the administrator permission"


def test_allowlist_group_permission_hides_from_non_admins():
    perms = allowlist_group.default_permissions
    assert perms is not None
    non_admin = discord.Permissions.none()
    assert not non_admin.administrator
    assert not (perms <= non_admin)
