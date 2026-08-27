"""Tool: manage_server — unified moderation and channel management actions."""

from __future__ import annotations

from datetime import timedelta

import discord
from discord.utils import utcnow

ACTIONS = {
    "kick":             "Kick a member from the server",
    "ban":              "Ban a member from the server",
    "unban":            "Unban a user by ID",
    "timeout":          "Temporarily mute a member (Discord timeout)",
    "remove_timeout":   "Remove an active timeout from a member",
    "create_channel":   "Create a new text, voice, or forum channel",
    "delete_channel":   "Permanently delete a channel",
    "rename_channel":   "Rename a channel",
    "move_member":      "Move a member to a different voice channel",
}


async def _resolve_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            return None
    return member


async def manage_server(
    guild: discord.Guild,
    action: str,
    user_id: int | None = None,
    reason: str | None = None,
    delete_message_days: int = 0,
    duration_minutes: int | None = None,
    channel_id: int | None = None,
    new_name: str | None = None,
    channel_type: str = "text",
    category_id: int | None = None,
    voice_channel_id: int | None = None,
) -> dict:
    """Execute a moderation or channel management action."""
    reason_tag = f"Warden: {reason}" if reason else "Warden"

    match action:
        # ------------------------------------------------------------------
        case "kick":
            if user_id is None:
                return {"error": "kick requires user_id"}
            member = await _resolve_member(guild, user_id)
            if member is None:
                return {"error": f"Member {user_id} not found."}
            try:
                await member.kick(reason=reason_tag)
                return {"ok": f"Kicked {member.display_name}."}
            except discord.Forbidden:
                return {"error": "Missing permission to kick this member."}
            except discord.HTTPException as e:
                return {"error": str(e)}

        # ------------------------------------------------------------------
        case "ban":
            if user_id is None:
                return {"error": "ban requires user_id"}
            member = await _resolve_member(guild, user_id)
            if member is None:
                return {"error": f"Member {user_id} not found."}
            days = max(0, min(7, delete_message_days))
            try:
                await guild.ban(member, reason=reason_tag, delete_message_days=days)
                return {"ok": f"Banned {member.display_name}."}
            except discord.Forbidden:
                return {"error": "Missing permission to ban this member."}
            except discord.HTTPException as e:
                return {"error": str(e)}

        # ------------------------------------------------------------------
        case "unban":
            if user_id is None:
                return {"error": "unban requires user_id"}
            try:
                user = await guild.fetch_ban(discord.Object(id=user_id))
                await guild.unban(user.user, reason=reason_tag)
                return {"ok": f"Unbanned {user.user}."}
            except discord.NotFound:
                return {"error": f"No active ban found for user ID {user_id}."}
            except discord.Forbidden:
                return {"error": "Missing permission to unban members."}
            except discord.HTTPException as e:
                return {"error": str(e)}

        # ------------------------------------------------------------------
        case "timeout":
            if user_id is None:
                return {"error": "timeout requires user_id"}
            if not duration_minutes or duration_minutes <= 0:
                return {"error": "timeout requires a positive duration_minutes"}
            member = await _resolve_member(guild, user_id)
            if member is None:
                return {"error": f"Member {user_id} not found."}
            until = utcnow() + timedelta(minutes=duration_minutes)
            try:
                await member.timeout(until, reason=reason_tag)
                return {"ok": f"Timed out {member.display_name} for {duration_minutes} minutes."}
            except discord.Forbidden:
                return {"error": "Missing permission to timeout this member."}
            except discord.HTTPException as e:
                return {"error": str(e)}

        # ------------------------------------------------------------------
        case "remove_timeout":
            if user_id is None:
                return {"error": "remove_timeout requires user_id"}
            member = await _resolve_member(guild, user_id)
            if member is None:
                return {"error": f"Member {user_id} not found."}
            if not member.is_timed_out():
                return {"info": f"{member.display_name} is not currently timed out."}
            try:
                await member.timeout(None, reason=reason_tag)
                return {"ok": f"Removed timeout from {member.display_name}."}
            except discord.Forbidden:
                return {"error": "Missing permission to remove timeout."}
            except discord.HTTPException as e:
                return {"error": str(e)}

        # ------------------------------------------------------------------
        case "create_channel":
            if not new_name:
                return {"error": "create_channel requires new_name"}
            category = None
            if category_id:
                category = guild.get_channel(category_id)
                if category and not isinstance(category, discord.CategoryChannel):
                    return {"error": f"Channel {category_id} is not a category."}
            try:
                match channel_type:
                    case "voice":
                        ch = await guild.create_voice_channel(new_name, category=category, reason=reason_tag)
                    case "forum":
                        ch = await guild.create_forum(new_name, category=category, reason=reason_tag)
                    case _:
                        ch = await guild.create_text_channel(new_name, category=category, reason=reason_tag)
                return {"ok": f"Created #{ch.name} (id: {ch.id})."}
            except discord.Forbidden:
                return {"error": "Missing permission to create channels."}
            except discord.HTTPException as e:
                return {"error": str(e)}

        # ------------------------------------------------------------------
        case "delete_channel":
            if channel_id is None:
                return {"error": "delete_channel requires channel_id"}
            channel = guild.get_channel(channel_id)
            if channel is None:
                return {"error": f"Channel {channel_id} not found."}
            name = channel.name
            try:
                await channel.delete(reason=reason_tag)
                return {"ok": f"Deleted #{name}."}
            except discord.Forbidden:
                return {"error": "Missing permission to delete this channel."}
            except discord.HTTPException as e:
                return {"error": str(e)}

        # ------------------------------------------------------------------
        case "rename_channel":
            if channel_id is None or not new_name:
                return {"error": "rename_channel requires channel_id and new_name"}
            channel = guild.get_channel(channel_id)
            if channel is None or not isinstance(channel, discord.abc.GuildChannel):
                return {"error": f"Channel {channel_id} not found."}
            old_name = channel.name
            try:
                await channel.edit(name=new_name, reason=reason_tag)
                return {"ok": f"Renamed #{old_name} → #{new_name}."}
            except discord.Forbidden:
                return {"error": "Missing permission to rename this channel."}
            except discord.HTTPException as e:
                return {"error": str(e)}

        # ------------------------------------------------------------------
        case "move_member":
            if user_id is None or voice_channel_id is None:
                return {"error": "move_member requires user_id and voice_channel_id"}
            member = await _resolve_member(guild, user_id)
            if member is None:
                return {"error": f"Member {user_id} not found."}
            if member.voice is None:
                return {"error": f"{member.display_name} is not in a voice channel."}
            vc = guild.get_channel(voice_channel_id)
            if vc is None or not isinstance(vc, discord.VoiceChannel):
                return {"error": f"Voice channel {voice_channel_id} not found."}
            try:
                await member.move_to(vc, reason=reason_tag)
                return {"ok": f"Moved {member.display_name} to #{vc.name}."}
            except discord.Forbidden:
                return {"error": "Missing permission to move this member."}
            except discord.HTTPException as e:
                return {"error": str(e)}

        # ------------------------------------------------------------------
        case _:
            return {"error": f"Unknown action '{action}'. Valid actions: {', '.join(ACTIONS)}"}
