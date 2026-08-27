"""Tools: set_reminder, set_birthday, list_reminders, delete_reminder."""

from __future__ import annotations

import calendar
from datetime import datetime, timezone, timedelta

import aiosqlite

from bot.storage.db import connect


def _next_repeat(remind_at: datetime, repeat: str) -> datetime:
    """Advance a datetime by one repeat interval."""
    match repeat:
        case "daily":
            return remind_at + timedelta(days=1)
        case "weekly":
            return remind_at + timedelta(weeks=1)
        case "monthly":
            month = remind_at.month % 12 + 1
            year = remind_at.year + (1 if remind_at.month == 12 else 0)
            # clamp day to valid range for the target month
            day = min(remind_at.day, calendar.monthrange(year, month)[1])
            return remind_at.replace(year=year, month=month, day=day)
        case "yearly":
            year = remind_at.year + 1
            # handle Feb 29 → Feb 28 on non-leap years
            day = min(remind_at.day, calendar.monthrange(year, remind_at.month)[1])
            return remind_at.replace(year=year, day=day)
        case _:
            raise ValueError(f"Unknown repeat interval: {repeat}")


async def set_reminder(
    guild_id: int,
    created_by: int,
    target_user_id: int,
    message: str,
    remind_at: datetime,
    channel_id: int,
    repeat: str | None = None,
    category: str = "general",
    tag: str | None = None,
) -> dict:
    """Create a reminder. Returns the new reminder ID."""
    if remind_at.tzinfo is None:
        remind_at = remind_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc).isoformat()
    async with connect() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO reminders
                (guild_id, created_by, target_user_id, message, remind_at,
                 channel_id, repeat, category, tag, created_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                guild_id, created_by, target_user_id, message,
                remind_at.isoformat(), channel_id,
                repeat, category, tag, now,
            ),
        )
        reminder_id = cursor.lastrowid
        await conn.commit()

    return {
        "ok": f"Reminder set (id: {reminder_id}).",
        "reminder_id": reminder_id,
        "fires_at": remind_at.strftime("%Y-%m-%d %H:%M UTC"),
        "repeat": repeat,
    }


async def set_birthday(
    guild_id: int,
    created_by: int,
    person_name: str,
    month: int,
    day: int,
    channel_id: int,
    person_user_id: int | None = None,
) -> dict:
    """Register a yearly birthday reminder for a person."""
    now = datetime.now(timezone.utc)
    try:
        candidate = datetime(now.year, month, day, 9, 0, tzinfo=timezone.utc)
    except ValueError:
        return {"error": f"Invalid date: month={month} day={day}"}

    # If this year's birthday has already passed, schedule for next year
    next_birthday = candidate if candidate > now else candidate.replace(year=now.year + 1)

    ping_id = person_user_id if person_user_id is not None else created_by
    message = f"🎂 Today is **{person_name}**'s birthday! Wishing them a wonderful day! 🎉"

    return await set_reminder(
        guild_id=guild_id,
        created_by=created_by,
        target_user_id=ping_id,
        message=message,
        remind_at=next_birthday,
        channel_id=channel_id,
        repeat="yearly",
        category="birthday",
        tag=person_name,
    )


async def list_reminders(guild_id: int, user_id: int) -> dict:
    """List all active reminders created by this user."""
    async with connect() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT id, target_user_id, message, remind_at, channel_id,
                   repeat, category, tag
            FROM reminders
            WHERE guild_id = ? AND created_by = ? AND active = 1
            ORDER BY remind_at
            """,
            (guild_id, user_id),
        ) as cursor:
            rows = await cursor.fetchall()

    return {
        "count": len(rows),
        "reminders": [dict(r) for r in rows],
    }


async def delete_reminder(reminder_id: int, user_id: int) -> dict:
    """Cancel an active reminder (only the creator can delete it)."""
    async with connect() as conn:
        async with conn.execute(
            "SELECT id FROM reminders WHERE id = ? AND created_by = ? AND active = 1",
            (reminder_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return {"error": f"No active reminder #{reminder_id} found for your account."}
        await conn.execute(
            "UPDATE reminders SET active = 0 WHERE id = ?", (reminder_id,)
        )
        await conn.commit()

    return {"ok": f"Reminder #{reminder_id} cancelled."}


# ---------------------------------------------------------------------------
# Internal: used by the scheduler
# ---------------------------------------------------------------------------

async def fetch_due_reminders(now: datetime) -> list[dict]:
    """Return all active reminders whose remind_at has passed."""
    async with connect() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT id, guild_id, target_user_id, message, remind_at,
                   channel_id, repeat, category, tag
            FROM reminders
            WHERE active = 1 AND remind_at <= ?
            ORDER BY remind_at
            """,
            (now.isoformat(),),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def advance_or_deactivate(reminder_id: int, remind_at_str: str, repeat: str | None) -> None:
    """After firing: advance the next trigger time or mark inactive."""
    async with connect() as conn:
        if repeat:
            remind_at = datetime.fromisoformat(remind_at_str)
            if remind_at.tzinfo is None:
                remind_at = remind_at.replace(tzinfo=timezone.utc)
            next_dt = _next_repeat(remind_at, repeat)
            await conn.execute(
                "UPDATE reminders SET remind_at = ? WHERE id = ?",
                (next_dt.isoformat(), reminder_id),
            )
        else:
            await conn.execute(
                "UPDATE reminders SET active = 0 WHERE id = ?", (reminder_id,)
            )
        await conn.commit()
