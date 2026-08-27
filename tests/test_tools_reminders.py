"""Tests for the reminder/calendar tool functions."""

from datetime import datetime, timezone

import pytest

from bot.storage import db
from bot.tools.reminders import (
    _next_repeat,
    advance_or_deactivate,
    delete_reminder,
    fetch_due_reminders,
    list_reminders,
    set_birthday,
    set_reminder,
)

GUILD = 111
USER = 999
TARGET = 888
CHANNEL = 777


async def _make_reminder(remind_at: datetime, repeat=None, active=True):
    result = await set_reminder(
        guild_id=GUILD,
        created_by=USER,
        target_user_id=TARGET,
        message="Test reminder",
        channel_id=CHANNEL,
        remind_at=remind_at,
        repeat=repeat,
    )
    reminder_id = result["reminder_id"]
    if not active:
        await delete_reminder(reminder_id, USER)
    return reminder_id


# ---------------------------------------------------------------------------
# _next_repeat
# ---------------------------------------------------------------------------

def test_next_repeat_daily():
    dt = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)
    assert _next_repeat(dt, "daily") == datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc)


def test_next_repeat_weekly():
    dt = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)
    assert _next_repeat(dt, "weekly") == datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc)


def test_next_repeat_monthly_basic():
    dt = datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc)
    assert _next_repeat(dt, "monthly") == datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc)


def test_next_repeat_monthly_clamps_day():
    # Jan 31 → Feb 28 (2026 is not a leap year)
    dt = datetime(2026, 1, 31, 9, 0, tzinfo=timezone.utc)
    result = _next_repeat(dt, "monthly")
    assert result == datetime(2026, 2, 28, 9, 0, tzinfo=timezone.utc)


def test_next_repeat_monthly_december():
    dt = datetime(2026, 12, 10, 9, 0, tzinfo=timezone.utc)
    result = _next_repeat(dt, "monthly")
    assert result == datetime(2027, 1, 10, 9, 0, tzinfo=timezone.utc)


def test_next_repeat_yearly_basic():
    dt = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)
    assert _next_repeat(dt, "yearly") == datetime(2027, 8, 27, 9, 0, tzinfo=timezone.utc)


def test_next_repeat_yearly_feb29_clamps():
    # 2024 is a leap year; next yearly from Feb 29, 2024 → Feb 28, 2025
    dt = datetime(2024, 2, 29, 9, 0, tzinfo=timezone.utc)
    result = _next_repeat(dt, "yearly")
    assert result == datetime(2025, 2, 28, 9, 0, tzinfo=timezone.utc)


def test_next_repeat_unknown():
    dt = datetime(2026, 6, 15, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        _next_repeat(dt, "biannually")


# ---------------------------------------------------------------------------
# set_reminder
# ---------------------------------------------------------------------------

async def test_set_reminder_returns_id(tmp_db):
    remind_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
    result = await set_reminder(GUILD, USER, TARGET, "Do the thing", CHANNEL, remind_at=remind_at)
    assert "ok" in result
    assert "reminder_id" in result
    assert isinstance(result["reminder_id"], int)


async def test_set_reminder_stored_correctly(tmp_db):
    remind_at = datetime(2030, 6, 15, 10, 0, tzinfo=timezone.utc)
    result = await set_reminder(
        GUILD, USER, TARGET, "Buy milk", CHANNEL, remind_at=remind_at, repeat="weekly"
    )
    rid = result["reminder_id"]

    async with db.connect() as conn:
        async with conn.execute("SELECT message, repeat, active FROM reminders WHERE id=?", (rid,)) as cur:
            row = await cur.fetchone()

    assert row[0] == "Buy milk"
    assert row[1] == "weekly"
    assert row[2] == 1


async def test_set_reminder_missing_remind_at(tmp_db):
    result = await set_reminder(GUILD, USER, TARGET, "No time", CHANNEL)
    assert "error" in result


# ---------------------------------------------------------------------------
# set_birthday (wrapper)
# ---------------------------------------------------------------------------

async def test_set_birthday_future(tmp_db):
    now = datetime.now(timezone.utc)
    month = (now.month % 12) + 1  # always next month from now
    result = await set_birthday(GUILD, USER, "Alice", month, 15, CHANNEL)
    assert "ok" in result
    rid = result["reminder_id"]
    async with db.connect() as conn:
        async with conn.execute("SELECT remind_at, category, tag FROM reminders WHERE id=?", (rid,)) as cur:
            row = await cur.fetchone()
    fires_at = datetime.fromisoformat(row[0])
    if fires_at.tzinfo is None:
        fires_at = fires_at.replace(tzinfo=timezone.utc)
    assert fires_at > now
    assert row[1] == "birthday"
    assert row[2] == "Alice"


async def test_set_birthday_past_schedules_next_year(tmp_db):
    now = datetime.now(timezone.utc)
    result = await set_birthday(GUILD, USER, "Bob", 1, 1, CHANNEL)
    assert "ok" in result
    rid = result["reminder_id"]
    async with db.connect() as conn:
        async with conn.execute("SELECT remind_at FROM reminders WHERE id=?", (rid,)) as cur:
            row = await cur.fetchone()
    fires_at = datetime.fromisoformat(row[0])
    if fires_at.tzinfo is None:
        fires_at = fires_at.replace(tzinfo=timezone.utc)
    assert fires_at > now


async def test_set_birthday_invalid_date(tmp_db):
    result = await set_birthday(GUILD, USER, "Ghost", 13, 1, CHANNEL)
    assert "error" in result


# ---------------------------------------------------------------------------
# list_reminders
# ---------------------------------------------------------------------------

async def test_list_reminders_empty(tmp_db):
    result = await list_reminders(GUILD, USER)
    assert result["count"] == 0
    assert result["reminders"] == []


async def test_list_reminders_shows_active(tmp_db):
    future = datetime(2035, 1, 1, tzinfo=timezone.utc)
    await set_reminder(GUILD, USER, TARGET, "First", CHANNEL, remind_at=future)
    await set_reminder(GUILD, USER, TARGET, "Second", CHANNEL, remind_at=future)
    result = await list_reminders(GUILD, USER)
    assert result["count"] == 2


async def test_list_reminders_excludes_inactive(tmp_db):
    future = datetime(2035, 1, 1, tzinfo=timezone.utc)
    r = await set_reminder(GUILD, USER, TARGET, "Gone", CHANNEL, remind_at=future)
    await delete_reminder(r["reminder_id"], USER)
    result = await list_reminders(GUILD, USER)
    assert result["count"] == 0


# ---------------------------------------------------------------------------
# delete_reminder
# ---------------------------------------------------------------------------

async def test_delete_reminder_success(tmp_db):
    future = datetime(2035, 1, 1, tzinfo=timezone.utc)
    r = await set_reminder(GUILD, USER, TARGET, "Delete me", CHANNEL, remind_at=future)
    result = await delete_reminder(r["reminder_id"], USER)
    assert "ok" in result
    listed = await list_reminders(GUILD, USER)
    assert listed["count"] == 0


async def test_delete_reminder_wrong_user(tmp_db):
    future = datetime(2035, 1, 1, tzinfo=timezone.utc)
    r = await set_reminder(GUILD, USER, TARGET, "Mine", CHANNEL, remind_at=future)
    result = await delete_reminder(r["reminder_id"], user_id=12345)
    assert "error" in result


async def test_delete_reminder_not_found(tmp_db):
    result = await delete_reminder(99999, USER)
    assert "error" in result


# ---------------------------------------------------------------------------
# fetch_due_reminders
# ---------------------------------------------------------------------------

async def test_fetch_due_reminders_returns_past(tmp_db):
    past = datetime(2000, 1, 1, tzinfo=timezone.utc)
    await set_reminder(GUILD, USER, TARGET, "Overdue", CHANNEL, remind_at=past)
    due = await fetch_due_reminders(datetime.now(timezone.utc))
    assert len(due) == 1
    assert due[0]["message"] == "Overdue"


async def test_fetch_due_reminders_excludes_future(tmp_db):
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    await set_reminder(GUILD, USER, TARGET, "Not yet", CHANNEL, remind_at=future)
    due = await fetch_due_reminders(datetime.now(timezone.utc))
    assert due == []


async def test_fetch_due_reminders_excludes_inactive(tmp_db):
    past = datetime(2000, 1, 1, tzinfo=timezone.utc)
    r = await set_reminder(GUILD, USER, TARGET, "Inactive past", CHANNEL, remind_at=past)
    await delete_reminder(r["reminder_id"], USER)
    due = await fetch_due_reminders(datetime.now(timezone.utc))
    assert due == []


# ---------------------------------------------------------------------------
# advance_or_deactivate
# ---------------------------------------------------------------------------

async def test_advance_or_deactivate_repeat(tmp_db):
    remind_at = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)
    r = await set_reminder(GUILD, USER, TARGET, "Annual", CHANNEL, remind_at=remind_at, repeat="yearly")
    rid = r["reminder_id"]

    await advance_or_deactivate(rid, remind_at.isoformat(), "yearly")

    async with db.connect() as conn:
        async with conn.execute("SELECT remind_at, active FROM reminders WHERE id=?", (rid,)) as cur:
            row = await cur.fetchone()

    new_dt = datetime.fromisoformat(row[0])
    if new_dt.tzinfo is None:
        new_dt = new_dt.replace(tzinfo=timezone.utc)
    assert new_dt.year == 2027
    assert row[1] == 1


async def test_advance_or_deactivate_oneshot(tmp_db):
    remind_at = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)
    r = await set_reminder(GUILD, USER, TARGET, "Once", CHANNEL, remind_at=remind_at)
    rid = r["reminder_id"]

    await advance_or_deactivate(rid, remind_at.isoformat(), None)

    async with db.connect() as conn:
        async with conn.execute("SELECT active FROM reminders WHERE id=?", (rid,)) as cur:
            row = await cur.fetchone()

    assert row[0] == 0
