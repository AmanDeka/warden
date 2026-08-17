"""Gemini tool-call loop."""

import json
import os
from datetime import datetime, timezone

import discord
from google.genai import types

from bot.agent.system_prompt import SYSTEM_PROMPT
from bot.agent.tool_schemas import TOOL_SCHEMAS, dispatch
from bot.storage import db
from bot.utils.formatting import status_embed
from bot.utils.gemini import get_client

MAX_ITERATIONS = 5
MAX_HISTORY_TURNS = 20
MODEL = "gemini-2.0-flash"

GUILD_ID = os.getenv("GUILD_ID")


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

async def _load_history(user_id: int) -> list[types.Content]:
    """Load the last MAX_HISTORY_TURNS turns for a user, oldest-first."""
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
        types.Content(role=row[0], parts=[types.Part.from_text(row[1])])
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
# Main entry point
# ---------------------------------------------------------------------------

async def run(
    message: discord.Message,
    guild: discord.Guild | None,
    bot_user: discord.ClientUser,
    status_msg: discord.Message,
) -> str:
    """Drive the Gemini function-calling loop and return the final answer text.

    Edits `status_msg` in place at each step so the user sees live progress.
    Saves the completed user+model turn to conversation history.
    Logs every tool call to the audit table.
    """
    if GUILD_ID is None:
        raise RuntimeError("GUILD_ID is not set. Load your .env file before starting the bot.")

    user = message.author
    channel_id = message.channel.id
    user_text = _strip_mention(message.content, bot_user.id)

    history = await _load_history(user.id)
    context_block = _build_context(guild, user)

    # Prepend a context block so Gemini always knows the channel list and who is asking.
    first_message = f"[Server context]\n{context_block}\n\n{user_text}"

    client = get_client()
    chat = client.aio.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
        ),
        history=history,
    )

    await status_msg.edit(embed=status_embed("🧠 Thinking..."))
    response = await chat.send_message(first_message)

    for _ in range(MAX_ITERATIONS):
        parts = response.candidates[0].content.parts
        function_calls = [p.function_call for p in parts if p.function_call is not None]

        if not function_calls:
            break

        tool_response_parts: list[types.Part] = []

        for fc in function_calls:
            tool_name = fc.name
            args = dict(fc.args)

            await status_msg.edit(embed=status_embed(f"🔧 `{tool_name}`..."))

            try:
                result = await dispatch(tool_name, args)
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

        response = await chat.send_message(
            types.Content(role="user", parts=tool_response_parts)
        )

    final_text = response.text or "_(no response)_"

    await _save_turn(user.id, channel_id, "user", user_text)
    await _save_turn(user.id, channel_id, "model", final_text)

    return final_text


async def run_from_slash(
    question: str,
    user: discord.Member | discord.User,
    guild: discord.Guild | None,
    bot_user: discord.ClientUser,
    status_msg: discord.Message,
) -> str:
    """Same tool-call loop as ``run()``, but invoked from the /ask slash command.

    Accepts a plain question string and the interaction user directly, rather
    than a full ``discord.Message``.  Conversation history is keyed by user_id
    so continuity is preserved across both mention-based and slash invocations.
    """
    if GUILD_ID is None:
        raise RuntimeError("GUILD_ID is not set. Load your .env file before starting the bot.")

    channel_id = status_msg.channel.id
    history = await _load_history(user.id)
    context_block = _build_context(guild, user)

    first_message = f"[Server context]\n{context_block}\n\n{question}"

    client = get_client()
    chat = client.aio.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
        ),
        history=history,
    )

    await status_msg.edit(embed=status_embed("🧠 Thinking..."))
    response = await chat.send_message(first_message)

    for _ in range(MAX_ITERATIONS):
        parts = response.candidates[0].content.parts
        function_calls = [p.function_call for p in parts if p.function_call is not None]

        if not function_calls:
            break

        tool_response_parts: list[types.Part] = []

        for fc in function_calls:
            tool_name = fc.name
            args = dict(fc.args)

            await status_msg.edit(embed=status_embed(f"🔧 `{tool_name}`..."))

            try:
                result = await dispatch(tool_name, args)
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

        response = await chat.send_message(
            types.Content(role="user", parts=tool_response_parts)
        )

    final_text = response.text or "_(no response)_"

    await _save_turn(user.id, channel_id, "user", question)
    await _save_turn(user.id, channel_id, "model", final_text)

    return final_text
