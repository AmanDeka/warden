"""Diff preview + reaction-based (✅/❌) confirmation flow via the status box."""

import asyncio
import discord

from bot.utils.formatting import status_embed

CONFIRM_EMOJI = "✅"
CANCEL_EMOJI = "❌"
TIMEOUT = 60  # seconds


async def request_confirmation(
    status_msg: discord.Message,
    diff_text: str,
    requester: discord.Member | discord.User,
    client: discord.Client,
) -> bool:
    """Edit the status box to show the proposed diff and wait for a ✅/❌ reaction.

    Returns True if the requester confirmed, False if they cancelled or the
    60-second window expired.  Edits the status box to reflect the outcome
    before returning so the caller doesn't need to clean up.
    """
    embed = discord.Embed(
        description=(
            f"⚠️ **Proposed change:**\n{diff_text}\n\n"
            f"React {CONFIRM_EMOJI} to confirm or {CANCEL_EMOJI} to cancel."
        ),
        color=discord.Color.orange(),
    )
    await status_msg.edit(embed=embed)
    await status_msg.add_reaction(CONFIRM_EMOJI)
    await status_msg.add_reaction(CANCEL_EMOJI)

    def check(reaction: discord.Reaction, user: discord.User) -> bool:
        return (
            user.id == requester.id
            and reaction.message.id == status_msg.id
            and str(reaction.emoji) in (CONFIRM_EMOJI, CANCEL_EMOJI)
        )

    try:
        reaction, _ = await client.wait_for("reaction_add", timeout=TIMEOUT, check=check)
        confirmed = str(reaction.emoji) == CONFIRM_EMOJI
    except asyncio.TimeoutError:
        confirmed = False

    if confirmed:
        await status_msg.edit(embed=status_embed("✅ Confirmed — applying..."))
    else:
        await status_msg.edit(embed=status_embed("❌ Cancelled"))

    return confirmed
