"""Check requester roles against the owner-configured allowlist for write tools."""

import discord
from bot.storage import db


async def is_allowed(member: discord.Member) -> bool:
    """Return True if any of the member's roles is on the PermissionAllowlist."""
    allowlist = await db.get_allowlist_role_ids()
    member_role_ids = {r.id for r in member.roles}
    return bool(allowlist & member_role_ids)


async def add_to_allowlist(role: discord.Role, added_by: discord.Member) -> None:
    await db.add_allowlist_role(role.id, role.guild.id, added_by.id)


async def remove_from_allowlist(role: discord.Role) -> bool:
    """Remove role from allowlist. Returns False if it wasn't listed."""
    allowlist = await db.get_allowlist_role_ids()
    if role.id not in allowlist:
        return False
    await db.remove_allowlist_role(role.id)
    return True


async def list_allowlist() -> list[dict]:
    """Return allowlist entries with role_id, added_by, added_at."""
    return await db.get_allowlist_entries()
