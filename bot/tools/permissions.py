"""Tools: list_permissions, list_roles, get_member_roles, and Phase 3 write tools."""

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


# ---------------------------------------------------------------------------
# Phase 3 — write tools
# ---------------------------------------------------------------------------

_REQUIRED_TEXT_PERMS = [
    "view_channel", "read_message_history", "send_messages", "embed_links", "attach_files",
]
_REQUIRED_VOICE_PERMS = ["view_channel", "connect", "speak"]


def _build_overwrite(allow: list[str], deny: list[str]) -> discord.PermissionOverwrite:
    ow = discord.PermissionOverwrite()
    for perm in allow:
        setattr(ow, perm, True)
    for perm in deny:
        setattr(ow, perm, False)
    return ow


async def _resolve_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            return None
    return member


async def assign_role(guild: discord.Guild, user_id: int, role_id: int) -> dict:
    """Add a role to a member."""
    member = await _resolve_member(guild, user_id)
    if member is None:
        return {"error": f"Member {user_id} not found in this server."}

    role = guild.get_role(role_id)
    if role is None:
        return {"error": f"Role {role_id} not found."}

    if role in member.roles:
        return {"info": f"{member.display_name} already has @{role.name}."}

    try:
        await member.add_roles(role, reason="Warden: assign_role tool")
        return {"ok": f"Assigned @{role.name} to {member.display_name}."}
    except discord.Forbidden:
        return {
            "error": (
                f"Missing permission to assign @{role.name}. "
                "Warden's role must be higher in the hierarchy than the target role."
            )
        }
    except discord.HTTPException as exc:
        return {"error": f"Discord API error: {exc}"}


async def remove_role(guild: discord.Guild, user_id: int, role_id: int) -> dict:
    """Remove a role from a member."""
    member = await _resolve_member(guild, user_id)
    if member is None:
        return {"error": f"Member {user_id} not found in this server."}

    role = guild.get_role(role_id)
    if role is None:
        return {"error": f"Role {role_id} not found."}

    if role not in member.roles:
        return {"info": f"{member.display_name} does not have @{role.name}."}

    try:
        await member.remove_roles(role, reason="Warden: remove_role tool")
        return {"ok": f"Removed @{role.name} from {member.display_name}."}
    except discord.Forbidden:
        return {
            "error": (
                f"Missing permission to remove @{role.name}. "
                "Warden's role must be higher in the hierarchy than the target role."
            )
        }
    except discord.HTTPException as exc:
        return {"error": f"Discord API error: {exc}"}


async def set_channel_permission(
    guild: discord.Guild,
    channel_id: int,
    target_id: int,
    allow: list[str] | None = None,
    deny: list[str] | None = None,
) -> dict:
    """Set a permission overwrite for a role or member on a channel."""
    channel = guild.get_channel(channel_id)
    if channel is None or not isinstance(channel, discord.abc.GuildChannel):
        return {"error": f"Channel {channel_id} not found."}

    # target can be a role or a member
    target: discord.Role | discord.Member | None = guild.get_role(target_id)
    if target is None:
        target = await _resolve_member(guild, target_id)
    if target is None:
        return {"error": f"No role or member found with ID {target_id}."}

    overwrite = _build_overwrite(allow or [], deny or [])

    try:
        await channel.set_permissions(target, overwrite=overwrite, reason="Warden: set_channel_permission tool")
        target_label = f"@{target.name}" if isinstance(target, discord.Role) else target.display_name
        return {"ok": f"Permission overwrite set on #{channel.name} for {target_label}."}
    except discord.Forbidden:
        return {"error": "Missing Manage Channel permission to set overwrites."}
    except discord.HTTPException as exc:
        return {"error": f"Discord API error: {exc}"}


async def create_role(
    guild: discord.Guild,
    name: str,
    permissions: list[str] | None = None,
    color: str | None = None,
) -> dict:
    """Create a new role with the given name, permissions, and optional hex color."""
    perm_obj = discord.Permissions.none()
    invalid = []
    for perm in (permissions or []):
        if hasattr(perm_obj, perm):
            setattr(perm_obj, perm, True)
        else:
            invalid.append(perm)

    if invalid:
        return {"error": f"Unknown permission names: {invalid}"}

    color_obj = discord.Color.default()
    if color:
        try:
            color_obj = discord.Color(int(color.lstrip("#"), 16))
        except ValueError:
            return {"error": f"Invalid color '{color}'. Use a hex value like #ff0000."}

    try:
        role = await guild.create_role(
            name=name,
            permissions=perm_obj,
            color=color_obj,
            reason="Warden: create_role tool",
        )
        return {
            "ok": f"Created role @{role.name}.",
            "role_id": str(role.id),
            "permissions": _permission_names(role.permissions),
        }
    except discord.Forbidden:
        return {"error": "Missing Manage Roles permission to create a role."}
    except discord.HTTPException as exc:
        return {"error": f"Discord API error: {exc}"}


async def delete_role(guild: discord.Guild, role_id: int) -> dict:
    """Delete a role by ID."""
    role = guild.get_role(role_id)
    if role is None:
        return {"error": f"Role {role_id} not found."}

    if role.managed:
        return {"error": f"@{role.name} is managed by an integration and cannot be deleted."}

    name = role.name
    try:
        await role.delete(reason="Warden: delete_role tool")
        return {"ok": f"Deleted role @{name}."}
    except discord.Forbidden:
        return {
            "error": (
                f"Missing permission to delete @{name}. "
                "Warden's role must be higher in the hierarchy than the target role."
            )
        }
    except discord.HTTPException as exc:
        return {"error": f"Discord API error: {exc}"}


_DANGEROUS_PERMS = [
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "ban_members",
    "kick_members",
    "manage_webhooks",
    "manage_expressions",
    "manage_messages",
    "mention_everyone",
]


async def scan_bots(guild: discord.Guild) -> dict:
    """List all bots in the guild with their roles and flagged dangerous permissions."""
    bots = [m for m in guild.members if m.bot]

    entries = []
    for bot in sorted(bots, key=lambda m: m.display_name.lower()):
        roles = [r for r in bot.roles if not r.is_default()]
        effective = bot.guild_permissions
        dangerous = [p for p in _DANGEROUS_PERMS if getattr(effective, p, False)]
        entries.append({
            "name": bot.display_name,
            "id": str(bot.id),
            "joined_at": bot.joined_at.isoformat() if bot.joined_at else None,
            "roles": [
                {"name": r.name, "id": str(r.id), "position": r.position}
                for r in sorted(roles, key=lambda r: r.position, reverse=True)
            ],
            "dangerous_permissions": dangerous,
            "has_administrator": effective.administrator,
        })

    return {
        "bot_count": len(bots),
        "bots": entries,
        "flagged": [b for b in entries if b["dangerous_permissions"]],
    }


async def fix_bot_access(
    guild: discord.Guild,
    channel_id: int,
    bot_name_or_id: str,
) -> dict:
    """Diagnose why another bot can't operate in a channel and propose a minimal fix.

    Walks the effective permission stack (server roles → category → channel overwrite),
    identifies which required permissions are missing, and returns a proposed overwrite.
    """
    channel = guild.get_channel(channel_id)
    if channel is None or not isinstance(channel, discord.abc.GuildChannel):
        return {"error": f"Channel {channel_id} not found."}

    # resolve the bot member by ID or display name
    target_member: discord.Member | None = None
    try:
        target_member = guild.get_member(int(bot_name_or_id))
    except ValueError:
        pass

    if target_member is None:
        name_lower = bot_name_or_id.lower()
        target_member = next(
            (m for m in guild.members if m.bot and name_lower in m.display_name.lower()),
            None,
        )

    if target_member is None:
        return {"error": f"Bot '{bot_name_or_id}' not found in this server."}

    if not target_member.bot:
        return {"error": f"{target_member.display_name} is not a bot account."}

    is_voice = isinstance(channel, discord.VoiceChannel)
    required = _REQUIRED_VOICE_PERMS if is_voice else _REQUIRED_TEXT_PERMS
    effective = channel.permissions_for(target_member)

    missing = [p for p in required if not getattr(effective, p, False)]

    # Walk the stack to explain each missing permission
    stack_report = []
    for perm in missing:
        sources = []

        # 1. server-level (roles)
        for role in target_member.roles:
            if getattr(role.permissions, perm, False):
                sources.append(f"granted by @{role.name} (server role)")

        # 2. category overwrite
        if channel.category:
            for target, ow in channel.category.overwrites.items():
                val = getattr(ow, perm, None)
                if val is not None:
                    label = f"@{target.name}" if isinstance(target, discord.Role) else target.display_name
                    sources.append(
                        f"{'allowed' if val else 'denied'} by {label} overwrite on category #{channel.category.name}"
                    )

        # 3. channel overwrite
        for target, ow in channel.overwrites.items():
            val = getattr(ow, perm, None)
            if val is not None:
                label = f"@{target.name}" if isinstance(target, discord.Role) else target.display_name
                sources.append(
                    f"{'allowed' if val else 'denied'} by {label} overwrite on #{channel.name}"
                )

        stack_report.append({
            "permission": perm,
            "effective": False,
            "stack": sources if sources else ["not granted at any level"],
        })

    if not missing:
        return {
            "ok": (
                f"{target_member.display_name} already has all required permissions "
                f"in #{channel.name}."
            ),
            "effective_permissions": {p: getattr(effective, p, False) for p in required},
        }

    # Propose the minimal channel-level overwrite that fixes all missing permissions
    proposed_allow = missing

    return {
        "bot": target_member.display_name,
        "channel": channel.name,
        "missing_permissions": missing,
        "diagnosis": stack_report,
        "proposed_fix": {
            "action": "set_channel_permission",
            "channel_id": str(channel_id),
            "target_id": str(target_member.id),
            "allow": proposed_allow,
            "deny": [],
            "note": (
                "Apply this overwrite to grant the minimum permissions needed. "
                "Use set_channel_permission with the proposed args to apply it."
            ),
        },
    }
