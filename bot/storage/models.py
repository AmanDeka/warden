"""Dataclasses for storage rows."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime


@dataclass
class MessageIndexEntry:
    message_id: int
    guild_id: int
    channel_id: int
    author_id: int
    content: str | None
    attachments: str  # JSON
    embeds: str       # JSON
    created_at: datetime
    edited_at: datetime | None = None
    deleted_at: datetime | None = None


@dataclass
class AuditLogEntry:
    id: int | None
    guild_id: int
    tool_name: str
    args: str  # JSON
    requester_id: int
    result: str | None
    executed_at: datetime


@dataclass
class ConversationContext:
    id: int | None
    guild_id: int
    user_id: int
    role: str  # 'user' or 'model'
    content: str
    channel_id: int
    created_at: datetime


@dataclass
class PermissionAllowlist:
    role_id: int
    guild_id: int
    added_by: int
    added_at: datetime
