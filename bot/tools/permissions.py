"""Tools: list/set/clean permissions, roles, and fix_bot_access."""

from __future__ import annotations
import discord


async def list_permissions(guild: discord.Guild, target_id: int) -> dict:
    # TODO: implement — covers both channel and role targets
    raise NotImplementedError


async def list_roles(guild: discord.Guild) -> list[dict]:
    # TODO: implement
    raise NotImplementedError


async def get_member_roles(guild: discord.Guild, user_id: int) -> list[dict]:
    # TODO: implement
    raise NotImplementedError


async def assign_role(guild: discord.Guild, user_id: int, role_id: int) -> None:
    # TODO: implement — write-tier, requires auth + confirmation
    raise NotImplementedError


async def remove_role(guild: discord.Guild, user_id: int, role_id: int) -> None:
    # TODO: implement — write-tier, requires auth + confirmation
    raise NotImplementedError


async def set_channel_permission(
    guild: discord.Guild,
    channel_id: int,
    target_id: int,
    allow: list[str],
    deny: list[str],
) -> None:
    # TODO: implement — write-tier, requires auth + confirmation
    raise NotImplementedError


async def clean_permissions(
    guild: discord.Guild,
    channel_id: int,
    policy: str = "sync_to_category",
) -> None:
    # TODO: implement — write-tier, requires auth + confirmation
    raise NotImplementedError


async def create_role(
    guild: discord.Guild, name: str, permissions: list[str], color: int = 0
) -> discord.Role:
    # TODO: implement — write-tier, requires auth + confirmation
    raise NotImplementedError


async def delete_role(guild: discord.Guild, role_id: int) -> None:
    # TODO: implement — write-tier, requires auth + confirmation
    raise NotImplementedError


async def fix_bot_access(guild: discord.Guild, channel_id: int, bot_id: int) -> dict:
    # TODO: walk effective permission stack and propose minimal fix
    raise NotImplementedError
