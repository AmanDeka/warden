"""Tools: set_reminder, list_reminders, delete_reminder."""

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
    channel_id: int,
    remind_at: datetime | None = None,
    repeat: str | None = None,
    category: str = "general",
    tag: str | None = None,
    birthday_month: int | None = None,
    birthday_day: int | None = None,
) -> dict:
    """Create a reminder or birthday reminder. Returns the new reminder ID.

    For birthdays: set category='birthday', provide birthday_month and birthday_day,
    and set tag to the person's name. remind_at is calculated automatically.
    For general reminders: provide remind_at as a UTC datetime.
    """
    now_dt = datetime.now(timezone.utc)

    if category == "birthday":
        if birthday_month is None or birthday_day is None:
            return {"error": "birthday_month and birthday_day are required when category='birthday'."}
        try:
            candidate = datetime(now_dt.year, birthday_month, birthday_day, 9, 0, tzinfo=timezone.utc)
        except ValueError:
            return {"error": f"Invalid date: month={birthday_month} day={birthday_day}"}
        remind_at = candidate if candidate > now_dt else candidate.replace(year=now_dt.year + 1)
        repeat = repeat or "yearly"
    else:
        if remind_at is None:
            return {"error": "remind_at is required for non-birthday reminders."}
        if remind_at.tzinfo is None:
            remind_at = remind_at.replace(tzinfo=timezone.utc)

    now = now_dt.isoformat()
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
    """Register a yearly birthday reminder. Wrapper over set_reminder."""
    ping_id = person_user_id if person_user_id is not None else created_by
    message = f"🎂 Today is **{person_name}**'s birthday! Wishing them a wonderful day! 🎉"
    return await set_reminder(
        guild_id=guild_id,
        created_by=created_by,
        target_user_id=ping_id,
        message=message,
        channel_id=channel_id,
        category="birthday",
        tag=person_name,
        birthday_month=month,
        birthday_day=day,
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
