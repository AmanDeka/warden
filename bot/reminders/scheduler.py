"""Background task: fire due reminders every minute."""

from __future__ import annotations

import discord
from discord.ext import tasks
from datetime import datetime, timezone

from bot.tools.reminders import advance_or_deactivate, fetch_due_reminders
from bot.utils.formatting import status_embed

_bot: discord.Client | None = None


def _reminder_embed(message: str, target: discord.Member | discord.User | None, category: str) -> discord.Embed:
    if category == "birthday":
        color = discord.Color.gold()
        title = "🎂 Birthday Reminder"
    else:
        color = discord.Color.blurple()
        title = "⏰ Reminder"

    embed = discord.Embed(title=title, description=message, color=color)
    if target:
        embed.set_footer(text=f"For {target.display_name}")
    return embed


@tasks.loop(minutes=1)
async def _check_reminders() -> None:
    if _bot is None:
        return

    now = datetime.now(timezone.utc)
    due = await fetch_due_reminders(now)

    for row in due:
        reminder_id = row["id"]
        channel_id = int(row["channel_id"])
        target_user_id = int(row["target_user_id"])
        message = row["message"]
        repeat = row["repeat"]
        remind_at = row["remind_at"]
        category = row["category"]

        channel = _bot.get_channel(channel_id)
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            # Channel gone — deactivate rather than loop forever
            await advance_or_deactivate(reminder_id, remind_at, None)
            continue

        target = channel.guild.get_member(target_user_id) if hasattr(channel, "guild") else None

        try:
            ping = f"<@{target_user_id}>" if target_user_id else ""
            embed = _reminder_embed(message, target, category)
            await channel.send(content=ping, embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

        await advance_or_deactivate(reminder_id, remind_at, repeat)


@_check_reminders.before_loop
async def _before_check() -> None:
    if _bot is not None:
        await _bot.wait_until_ready()


def start(bot: discord.Client) -> None:
    global _bot
    _bot = bot
    if not _check_reminders.is_running():
        _check_reminders.start()
