"""Tools: get_audit_log, bulk_permission_audit."""

from __future__ import annotations
import discord


async def get_audit_log(
    guild: discord.Guild,
    action_type: discord.AuditLogAction | None = None,
    limit: int = 20,
) -> list[dict]:
    # TODO: implement
    raise NotImplementedError


async def bulk_permission_audit(guild: discord.Guild) -> list[dict]:
    # TODO: scan all channels, flag anomalies
    raise NotImplementedError
