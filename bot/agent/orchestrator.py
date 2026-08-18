"""Gemini tool-call loop."""

import json
import os
from datetime import datetime, timezone

import discord
from google.genai import types

from bot.agent.system_prompt import SYSTEM_PROMPT
from bot.agent.tool_schemas import TOOL_SCHEMAS, WRITE_TOOLS, describe_write_action, dispatch
from bot.guardrails import auth, confirmation
from bot.storage import db
from bot.utils.formatting import status_embed
from bot.utils.gemini import get_client

MAX_ITERATIONS = 15
MAX_HISTORY_TURNS = 20
MODEL = "gemini-3.5-flash"

GUILD_ID = int(os.environ["GUILD_ID"])


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

async def _load_history(user_id: int) -> list[types.Content]:
    sql = """
        SELECT role, content FROM conversation_context
        WHERE guild_id = ? AND user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """
    async with db.connect() as conn:
        async with conn.execute(sql, (GUILD_ID, user_id, MAX_HISTORY_TURNS)) as cursor:
            rows = await cursor.fetchall()

    return [
        types.Content(role=row[0], parts=[types.Part(text=row[1])])
        for row in reversed(rows)
    ]


async def _save_turn(user_id: int, channel_id: int, role: str, content: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with db.connect() as conn:
        await conn.execute(
            """
            INSERT INTO conversation_context
                (guild_id, user_id, role, content, channel_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (GUILD_ID, user_id, role, content, channel_id, now),
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

async def _log_tool_call(
    requester_id: int,
    tool_name: str,
    args: dict,
    result: object,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with db.connect() as conn:
        await conn.execute(
            """
            INSERT INTO audit_log
                (guild_id, tool_name, args, requester_id, result, executed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                GUILD_ID,
                tool_name,
                json.dumps(args),
                requester_id,
                json.dumps(result, default=str),
                now,
            ),
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# Context block
# ---------------------------------------------------------------------------

def _build_context(
    guild: discord.Guild | None,
    user: discord.Member | discord.User,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"Current time: {now}",
        f"Requesting user: {user.display_name} (id: {user.id})",
    ]
    if guild is not None:
        lines.insert(0, f"Guild: {guild.name} (id: {guild.id})")
        channels = [
            f"  #{ch.name} (id: {ch.id})"
            for ch in guild.text_channels
            if ch.permissions_for(guild.me).read_messages
        ]
        if channels:
            lines.append("Visible text channels:\n" + "\n".join(channels))
    return "\n".join(lines)


def _strip_mention(content: str, bot_id: int) -> str:
    return (
        content
        .replace(f"<@{bot_id}>", "")
        .replace(f"<@!{bot_id}>", "")
        .strip()
    )


# ---------------------------------------------------------------------------
# Shared tool-call loop
# ---------------------------------------------------------------------------

async def _run_loop(
    chat,
    user: discord.Member | discord.User,
    guild: discord.Guild | None,
    channel_id: int,
    user_text: str,
    status_msg: discord.Message,
    bot_client: discord.Client,
) -> str:
    """Drive the Gemini function-calling loop and return the final answer text.

    Handles write-tool auth checks and the ✅/❌ confirmation flow.
    Saves the completed turn to conversation history and logs every tool call.
    """
    await status_msg.edit(embed=status_embed("🧠 Thinking..."))
    first_message = f"[Server context]\n{_build_context(guild, user)}\n\n{user_text}"
    response = await chat.send_message(first_message)

    for _ in range(MAX_ITERATIONS):
        parts = response.candidates[0].content.parts
        function_calls = [p.function_call for p in parts if p.function_call is not None]

        if not function_calls:
            break

        tool_response_parts: list[types.Part] = []

        # --- Resolve member once per loop iteration (needed for auth checks) ---
        member = user
        if not isinstance(member, discord.Member) and guild is not None:
            try:
                member = await guild.fetch_member(user.id)
            except discord.NotFound:
                member = None

        # --- Batch-confirm all write tools in this round with a single prompt ---
        write_calls = [
            fc for fc in function_calls if fc.name in WRITE_TOOLS
        ]
        batch_confirmed: bool | None = None  # None = not yet asked

        if write_calls:
            # Auth check — applies to the whole batch
            if not isinstance(member, discord.Member) or not await auth.is_allowed(member):
                for fc in write_calls:
                    tool_response_parts.append(
                        types.Part.from_function_response(
                            name=fc.name,
                            response={"error": (
                                "Permission denied. Your roles are not on the "
                                "permissions allowlist. Ask the server owner to run "
                                "`/permissions-allowlist add @role`."
                            )},
                        )
                    )
                await status_msg.edit(embed=status_embed("🚫 Not authorised for write tools"))
                # Skip to sending tool_response_parts (which now contain all denials)
                response = await chat.send_message(tool_response_parts)
                continue

            # Build a combined diff for all write calls in this round
            diffs = []
            for fc in write_calls:
                diffs.append(describe_write_action(fc.name, dict(fc.args), guild))
            combined_diff = "\n".join(f"{i+1}. {d}" for i, d in enumerate(diffs))

            batch_confirmed = await confirmation.request_confirmation(
                status_msg, combined_diff, user, bot_client
            )
            if not batch_confirmed:
                for fc in write_calls:
                    tool_response_parts.append(
                        types.Part.from_function_response(
                            name=fc.name,
                            response={"cancelled": "The user cancelled this action."},
                        )
                    )
                response = await chat.send_message(tool_response_parts)
                continue

        for fc in function_calls:
            tool_name = fc.name
            args = dict(fc.args)

            # Write tools that were cancelled in the batch step — skip execution
            if tool_name in WRITE_TOOLS and batch_confirmed is False:
                continue

            # --- execute ---
            await status_msg.edit(embed=status_embed(f"🔧 `{tool_name}`..."))
            try:
                result = await dispatch(tool_name, args, guild=guild)
                await _log_tool_call(user.id, tool_name, args, result)
                tool_response_parts.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response={"result": result},
                    )
                )
                await status_msg.edit(embed=status_embed(f"✅ `{tool_name}` done"))
            except Exception as exc:
                tool_response_parts.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response={"error": str(exc)},
                    )
                )
                await status_msg.edit(embed=status_embed(f"⚠️ `{tool_name}` failed: {exc}"))

        response = await chat.send_message(tool_response_parts)

    final_text = response.text or "_(no response)_"

    await _save_turn(user.id, channel_id, "user", user_text)
    await _save_turn(user.id, channel_id, "model", final_text)

    return final_text


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

async def run(
    message: discord.Message,
    guild: discord.Guild | None,
    bot_user: discord.ClientUser,
    status_msg: discord.Message,
    bot_client: discord.Client,
) -> str:
    """Entry point for @mention / reply / DM invocations."""
    user = message.author
    user_text = _strip_mention(message.content, bot_user.id)
    history = await _load_history(user.id)

    client = get_client()
    chat = client.aio.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
        ),
        history=history,
    )

    return await _run_loop(
        chat, user, guild, message.channel.id, user_text, status_msg, bot_client
    )


async def run_from_slash(
    question: str,
    user: discord.Member | discord.User,
    guild: discord.Guild | None,
    bot_user: discord.ClientUser,
    status_msg: discord.Message,
    bot_client: discord.Client,
) -> str:
    """Entry point for the /ask slash command."""
    history = await _load_history(user.id)

    client = get_client()
    chat = client.aio.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
        ),
        history=history,
    )

    return await _run_loop(
        chat, user, guild, status_msg.channel.id, question, status_msg, bot_client
    )
