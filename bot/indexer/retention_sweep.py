"""Scheduled job: permanently purge soft-deleted rows older than 2 months."""

from datetime import datetime, timedelta, timezone
from bot.storage import db

RETENTION_DAYS = 60


async def sweep() -> int:
    """Delete rows where deleted_at < now - RETENTION_DAYS. Returns count purged."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    # TODO: implement DELETE FROM messages WHERE deleted_at IS NOT NULL AND deleted_at < cutoff
    return 0
