"""Tools: get_audit_log, bulk_permission_audit."""

from __future__ import annotations

import discord

_AUDIT_ACTIONS: dict[str, discord.AuditLogAction] = {
    "ban":                  discord.AuditLogAction.ban,
    "unban":                discord.AuditLogAction.unban,
    "kick":                 discord.AuditLogAction.kick,
    "member_update":        discord.AuditLogAction.member_update,
    "member_role_update":   discord.AuditLogAction.member_role_update,
    "role_create":          discord.AuditLogAction.role_create,
    "role_delete":          discord.AuditLogAction.role_delete,
    "role_update":          discord.AuditLogAction.role_update,
    "channel_create":       discord.AuditLogAction.channel_create,
    "channel_delete":       discord.AuditLogAction.channel_delete,
    "channel_update":       discord.AuditLogAction.channel_update,
    "overwrite_create":     discord.AuditLogAction.overwrite_create,
    "overwrite_update":     discord.AuditLogAction.overwrite_update,
    "overwrite_delete":     discord.AuditLogAction.overwrite_delete,
    "message_delete":       discord.AuditLogAction.message_delete,
    "message_bulk_delete":  discord.AuditLogAction.message_bulk_delete,
}

_DANGEROUS_PERMS = {
    "administrator",
    "manage_guild",
    "ban_members",
    "kick_members",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "mention_everyone",
}


def _serialize_entry(entry: discord.AuditLogEntry) -> dict:
    target_name = None
    if isinstance(entry.target, (discord.Role, discord.Member, discord.User)):
        target_name = getattr(entry.target, "display_name", None) or getattr(entry.target, "name", None)
    elif isinstance(entry.target, discord.abc.GuildChannel):
        target_name = entry.target.name

    changes = {}
    if entry.changes:
        for change in entry.changes:
            changes[change.attribute] = {
                "before": str(change.before) if change.before is not None else None,
                "after": str(change.after) if change.after is not None else None,
            }

    return {
        "action": entry.action.name,
        "user": entry.user.display_name if entry.user else "Unknown",
        "user_id": str(entry.user.id) if entry.user else None,
        "target": target_name,
        "reason": entry.reason,
        "changes": changes,
        "created_at": entry.created_at.isoformat(),
    }


async def get_audit_log(
    guild: discord.Guild,
    action_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Fetch recent audit log entries, optionally filtered by action type."""
    action = _AUDIT_ACTIONS.get(action_type) if action_type else None
    entries = []
    async for entry in guild.audit_logs(limit=limit, action=action):
        entries.append(_serialize_entry(entry))
    return entries


async def bulk_permission_audit(guild: discord.Guild) -> list[dict]:
    """Scan all channels for permission anomalies.

    Flags:
    - Orphaned overwrites (target role/member no longer exists)
    - @everyone granted dangerous permissions in a channel overwrite
    - Channels completely hidden from @everyone with no compensating role overwrite
    """
    anomalies: list[dict] = []

    for channel in guild.channels:
        if not isinstance(channel, discord.abc.GuildChannel):
            continue

        everyone_can_view = True
        any_role_can_view = False

        for target, overwrite in channel.overwrites.items():
            # Orphaned overwrite — target is not a known Role or Member
            if not isinstance(target, (discord.Role, discord.Member)):
                anomalies.append({
                    "channel": channel.name,
                    "channel_id": str(channel.id),
                    "issue": "orphaned_overwrite",
                    "detail": f"Overwrite for deleted target (id: {target.id})",
                })
                continue

            # @everyone with dangerous permissions
            if isinstance(target, discord.Role) and target.is_default():
                if overwrite.view_channel is False:
                    everyone_can_view = False
                granted = [
                    name for name, value in overwrite
                    if value is True and name in _DANGEROUS_PERMS
                ]
                if granted:
                    anomalies.append({
                        "channel": channel.name,
                        "channel_id": str(channel.id),
                        "issue": "everyone_dangerous_permission",
                        "detail": f"@everyone is granted: {', '.join(granted)}",
                    })

            # Track if any non-everyone role can view
            if isinstance(target, discord.Role) and not target.is_default():
                if overwrite.view_channel is True:
                    any_role_can_view = True

        # Channel invisible to @everyone with no role that can see it
        if not everyone_can_view and not any_role_can_view:
            anomalies.append({
                "channel": channel.name,
                "channel_id": str(channel.id),
                "issue": "inaccessible_channel",
                "detail": "Hidden from @everyone with no role overwrite granting access.",
            })

    return anomalies
