"""Tools: list_permissions, list_roles, get_member_roles."""

from __future__ import annotations

import discord


def _permission_names(perms: discord.Permissions) -> list[str]:
    return [name for name, value in perms if value]


def _overwrite_to_dict(
    target: discord.Role | discord.Member | discord.Object,
    overwrite: discord.PermissionOverwrite,
) -> dict:
    allow = [name for name, value in overwrite if value is True]
    deny = [name for name, value in overwrite if value is False]

    if isinstance(target, discord.Role):
        target_type, target_name = "role", target.name
    elif isinstance(target, discord.Member):
        target_type, target_name = "member", target.display_name
    else:
        target_type, target_name = "unknown", f"deleted (id: {target.id})"

    return {
        "target_type": target_type,
        "target_name": target_name,
        "target_id": str(target.id),
        "allow": allow,
        "deny": deny,
    }


async def list_permissions(guild: discord.Guild, target_id: int) -> dict:
    """Return permission info for a channel or role.

    Tries channel first, then role. Returns overwrites for channels and
    the full permission set for roles.
    """
    channel = guild.get_channel(target_id)
    if channel is not None and isinstance(channel, discord.abc.GuildChannel):
        synced = (
            channel.permissions_synced
            if hasattr(channel, "permissions_synced")
            else None
        )
        return {
            "type": "channel",
            "name": channel.name,
            "id": str(channel.id),
            "category": channel.category.name if channel.category else None,
            "synced_to_category": synced,
            "overwrites": [
                _overwrite_to_dict(target, ow)
                for target, ow in channel.overwrites.items()
            ],
        }

    role = guild.get_role(target_id)
    if role is not None:
        return {
            "type": "role",
            "name": role.name,
            "id": str(role.id),
            "color": str(role.color),
            "hoisted": role.hoist,
            "mentionable": role.mentionable,
            "position": role.position,
            "permissions": _permission_names(role.permissions),
        }

    return {"error": f"No channel or role found with ID {target_id}"}


async def list_roles(guild: discord.Guild) -> list[dict]:
    """Return all roles in the guild, sorted by position (highest first)."""
    return [
        {
            "name": role.name,
            "id": str(role.id),
            "color": str(role.color),
            "hoisted": role.hoist,
            "mentionable": role.mentionable,
            "position": role.position,
            "managed": role.managed,
            "permissions": _permission_names(role.permissions),
            "member_count": len(role.members),
        }
        for role in sorted(guild.roles, key=lambda r: r.position, reverse=True)
    ]


async def get_member_roles(guild: discord.Guild, user_id: int) -> dict:
    """Return the roles held by a specific member."""
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            return {"error": f"Member {user_id} not found in this server."}

    return {
        "user": member.display_name,
        "user_id": str(member.id),
        "roles": [
            {
                "name": role.name,
                "id": str(role.id),
                "position": role.position,
            }
            for role in sorted(member.roles, key=lambda r: r.position, reverse=True)
            if not role.is_default()
        ],
    }
