"""Diff preview + reaction-based (✅/❌) confirmation flow via the status box."""

import asyncio
import discord

CONFIRM_EMOJI = "✅"
CANCEL_EMOJI = "❌"
TIMEOUT = 60  # seconds


async def request_confirmation(
    status_msg: discord.Message,
    diff_text: str,
    requester: discord.Member,
) -> bool:
    """
    Edit the status box to show the proposed diff and wait for a reaction.
    Returns True if confirmed, False if cancelled or timed out.
    """
    embed = discord.Embed(
        description=f"⚠️ **Proposed change:**\n{diff_text}\n\nReact {CONFIRM_EMOJI} to confirm, {CANCEL_EMOJI} to cancel.",
        color=discord.Color.orange(),
    )
    await status_msg.edit(embed=embed)
    await status_msg.add_reaction(CONFIRM_EMOJI)
    await status_msg.add_reaction(CANCEL_EMOJI)

    def check(reaction: discord.Reaction, user: discord.User) -> bool:
        return (
            user == requester
            and reaction.message.id == status_msg.id
            and str(reaction.emoji) in (CONFIRM_EMOJI, CANCEL_EMOJI)
        )

    try:
        reaction, _ = await status_msg._state._get_client().wait_for(
            "reaction_add", timeout=TIMEOUT, check=check
        )
        confirmed = str(reaction.emoji) == CONFIRM_EMOJI
    except asyncio.TimeoutError:
        confirmed = False

    result_text = "✅ Applied" if confirmed else "❌ Cancelled"
    await status_msg.edit(embed=discord.Embed(description=result_text))
    return confirmed
