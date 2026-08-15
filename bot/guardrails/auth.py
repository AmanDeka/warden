"""Check requester roles against the owner-configured allowlist for write tools."""

import discord
from bot.storage import db


async def is_allowed(member: discord.Member) -> bool:
    """Return True if any of the member's roles is on the PermissionAllowlist."""
    role_ids = [r.id for r in member.roles]
    # TODO: query PermissionAllowlist table for matching role_ids
    return False


async def add_to_allowlist(role: discord.Role, added_by: discord.Member) -> None:
    # TODO: INSERT INTO permission_allowlist
    raise NotImplementedError


async def remove_from_allowlist(role: discord.Role) -> None:
    # TODO: DELETE FROM permission_allowlist WHERE role_id = ?
    raise NotImplementedError


async def list_allowlist() -> list[int]:
    # TODO: SELECT role_id FROM permission_allowlist
    return []
