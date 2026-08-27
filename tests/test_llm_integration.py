"""LLM integration tests — hit the real Gemini API and verify tool selection.

Run with:
    uv run pytest tests/test_llm_integration.py -v

Skipped automatically when GEMINI_API_KEY is not set or is the test placeholder.
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

# Load .env with override=True so the real key replaces the "test-key" placeholder
# that conftest.py sets via setdefault.
load_dotenv(override=True)

import pytest
from google import genai
from google.genai import types

from bot.agent.orchestrator import MODEL
from bot.agent.system_prompt import SYSTEM_PROMPT
from bot.agent.tool_schemas import TOOL_SCHEMAS

_KEY = os.environ.get("GEMINI_API_KEY", "")
_REAL_KEY = bool(_KEY) and _KEY != "test-key"

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(not _REAL_KEY, reason="Real GEMINI_API_KEY not available"),
]


@pytest.fixture(autouse=True)
async def _rate_limit_pause():
    """4-second pause between tests — keeps API calls under the 15 req/min free tier limit."""
    await asyncio.sleep(4)

# ---------------------------------------------------------------------------
# Fake server context (mirrors what _build_context produces in production)
# ---------------------------------------------------------------------------

_CONTEXT = """\
Guild: TestServer (id: 111111111111111111)
Current time: 2026-08-27 10:00 UTC
Requesting user: TestUser (id: 222222222222222222)
Visible text channels:
  #general (id: 333333333333333333)
  #announcements (id: 444444444444444444)
  #media (id: 555555555555555555)
  #staff (id: 666666666666666666)
  #birthday (id: 777777777777777777)\
"""

# Fake role/user IDs used in write-tool prompts
_ROLE_ID = "888888888888888888"
_USER_ID = "999999999999999999"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ask(prompt: str) -> list[types.FunctionCall]:
    """Send a prompt to Gemini and return all function calls from the first response."""
    client = genai.Client(api_key=_KEY)
    chat = client.aio.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
        ),
    )
    response = await chat.send_message(f"[Server context]\n{_CONTEXT}\n\n{prompt}")
    parts = response.candidates[0].content.parts
    return [p.function_call for p in parts if p.function_call is not None]


async def _first_tool(prompt: str) -> types.FunctionCall | None:
    calls = await _ask(prompt)
    return calls[0] if calls else None


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------

async def test_list_roles_selected():
    fc = await _first_tool("What roles exist in this server?")
    assert fc is not None
    assert fc.name == "list_roles"


async def test_list_roles_no_args():
    fc = await _first_tool("Show me all server roles")
    assert fc is not None
    assert fc.name == "list_roles"
    assert dict(fc.args) == {}


async def test_scan_bots_selected():
    fc = await _first_tool("List all bots in the server")
    assert fc is not None
    assert fc.name == "scan_bots"


async def test_bulk_permission_audit_selected():
    fc = await _first_tool("Audit permissions across all channels")
    assert fc is not None
    assert fc.name == "bulk_permission_audit"


async def test_get_audit_log_selected():
    fc = await _first_tool("Show me the recent audit log")
    assert fc is not None
    assert fc.name == "get_audit_log"


async def test_get_audit_log_with_limit():
    fc = await _first_tool("Show me the last 5 audit log entries")
    assert fc is not None
    assert fc.name == "get_audit_log"
    assert int(fc.args.get("limit", 20)) <= 10


# ---------------------------------------------------------------------------
# search_messages
# ---------------------------------------------------------------------------

async def test_search_messages_selected():
    fc = await _first_tool("Search for messages about deploy in #general")
    assert fc is not None
    assert fc.name == "search_messages"


async def test_search_messages_channel_id_resolved():
    fc = await _first_tool("Search for messages about deploy in #general")
    assert fc is not None
    assert fc.args.get("channel_id") == "333333333333333333"


async def test_search_messages_query_populated():
    fc = await _first_tool("Search for messages about deploy in #general")
    assert fc is not None
    assert "deploy" in fc.args.get("query", "").lower()


async def test_search_messages_author_filter():
    fc = await _first_tool(
        f"Find messages in #general sent by <@{_USER_ID}> about the outage"
    )
    assert fc is not None
    assert fc.name == "search_messages"
    assert fc.args.get("author_id") == _USER_ID


# ---------------------------------------------------------------------------
# summarize_channel
# ---------------------------------------------------------------------------

async def test_summarize_channel_selected():
    fc = await _first_tool("Summarize the last 50 messages in #announcements")
    assert fc is not None
    assert fc.name == "summarize_channel"


async def test_summarize_channel_id_resolved():
    fc = await _first_tool("Summarize #announcements")
    assert fc is not None
    assert fc.args.get("channel_id") == "444444444444444444"


async def test_summarize_channel_limit_passed():
    fc = await _first_tool("Summarize the last 30 messages in #general")
    assert fc is not None
    assert fc.name == "summarize_channel"
    assert int(fc.args.get("limit", 200)) <= 50


# ---------------------------------------------------------------------------
# find_media
# ---------------------------------------------------------------------------

async def test_find_media_selected():
    fc = await _first_tool("Find images posted in #media")
    assert fc is not None
    assert fc.name == "find_media"


async def test_find_media_channel_resolved():
    fc = await _first_tool("Find images in #media")
    assert fc is not None
    assert fc.args.get("channel_id") == "555555555555555555"


async def test_find_media_type_image():
    fc = await _first_tool("Find images in #general")
    assert fc is not None
    assert fc.args.get("media_type", "image") == "image"


async def test_find_media_type_video():
    fc = await _first_tool("Find video clips shared in #general")
    assert fc is not None
    assert fc.name == "find_media"
    assert fc.args.get("media_type") == "video"


# ---------------------------------------------------------------------------
# list_permissions
# ---------------------------------------------------------------------------

async def test_list_permissions_channel():
    fc = await _first_tool("What permissions does #general have?")
    assert fc is not None
    assert fc.name == "list_permissions"
    assert fc.args.get("target_id") == "333333333333333333"


async def test_get_member_roles_selected():
    fc = await _first_tool(f"What roles does <@{_USER_ID}> have?")
    assert fc is not None
    assert fc.name == "get_member_roles"
    assert fc.args.get("user_id") == _USER_ID


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

async def test_set_reminder_selected():
    fc = await _first_tool(
        "Remind me in #general tomorrow at 9am UTC to check the deployment"
    )
    assert fc is not None
    assert fc.name == "set_reminder"


async def test_set_reminder_message_populated():
    fc = await _first_tool(
        "Remind me in #general at 2026-09-01T09:00:00Z to submit the report"
    )
    assert fc is not None
    assert fc.name == "set_reminder"
    assert "report" in fc.args.get("message", "").lower()


async def test_set_reminder_channel_resolved():
    fc = await _first_tool(
        "Remind me in #general at 2026-09-01T09:00:00Z to submit the report"
    )
    assert fc is not None
    assert fc.args.get("channel_id") == "333333333333333333"


async def test_set_reminder_created_by_populated():
    fc = await _first_tool(
        "Remind me in #general at 2026-09-01T09:00:00Z to submit the report"
    )
    assert fc is not None
    assert fc.args.get("created_by") == "222222222222222222"


async def test_set_reminder_weekly_repeat():
    fc = await _first_tool(
        "Remind me every Monday in #general at 9am UTC to check the backups"
    )
    assert fc is not None
    assert fc.name == "set_reminder"
    assert fc.args.get("repeat") == "weekly"


async def test_set_birthday_selected():
    fc = await _first_tool(
        "Remember that Alex's birthday is on March 14. Post the reminder in #birthday"
    )
    assert fc is not None
    assert fc.name == "set_reminder"
    assert fc.args.get("category") == "birthday"


async def test_set_birthday_name_populated():
    # Person's name goes into the `tag` field on set_reminder
    fc = await _first_tool(
        "Remember that Alex's birthday is on March 14. Post the reminder in #birthday"
    )
    assert fc is not None
    name_field = (fc.args.get("tag", "") + fc.args.get("message", "")).lower()
    assert "alex" in name_field


async def test_set_birthday_date_populated():
    # Birthday date goes into birthday_month / birthday_day on set_reminder
    fc = await _first_tool(
        "Remember that Alex's birthday is on March 14. Post the reminder in #birthday"
    )
    assert fc is not None
    assert int(fc.args.get("birthday_month", 0)) == 3
    assert int(fc.args.get("birthday_day", 0)) == 14


async def test_set_birthday_channel_resolved():
    fc = await _first_tool(
        "Remember that Alex's birthday is on March 14. Post the reminder in #birthday"
    )
    assert fc is not None
    assert fc.args.get("channel_id") == "777777777777777777"


async def test_list_reminders_selected():
    fc = await _first_tool("Show me my active reminders")
    assert fc is not None
    assert fc.name == "list_reminders"
    assert fc.args.get("user_id") == "222222222222222222"


async def test_delete_reminder_selected():
    fc = await _first_tool("Cancel reminder number 5")
    assert fc is not None
    assert fc.name == "delete_reminder"
    assert int(fc.args.get("reminder_id", 0)) == 5


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------

async def test_assign_role_selected():
    fc = await _first_tool(
        f"Assign role id {_ROLE_ID} to user id {_USER_ID}"
    )
    assert fc is not None
    assert fc.name == "assign_role"
    assert fc.args.get("role_id") == _ROLE_ID
    assert fc.args.get("user_id") == _USER_ID


async def test_fix_bot_access_selected():
    fc = await _first_tool(
        "Why can't MEE6 access #general? Fix its permissions."
    )
    assert fc is not None
    assert fc.name == "fix_bot_access"
    assert fc.args.get("channel_id") == "333333333333333333"


# ---------------------------------------------------------------------------
# manage_server — moderation actions
# ---------------------------------------------------------------------------

async def test_kick_selected():
    fc = await _first_tool(f"Kick user id {_USER_ID} for spamming")
    assert fc is not None
    assert fc.name == "manage_server"
    assert fc.args.get("action") == "kick"
    assert fc.args.get("user_id") == _USER_ID


async def test_kick_reason_populated():
    fc = await _first_tool(f"Kick user id {_USER_ID} for spamming")
    assert fc is not None
    assert "spam" in fc.args.get("reason", "").lower()


async def test_ban_selected():
    fc = await _first_tool(f"Ban user id {_USER_ID} for repeated violations")
    assert fc is not None
    assert fc.name == "manage_server"
    assert fc.args.get("action") == "ban"
    assert fc.args.get("user_id") == _USER_ID


async def test_unban_selected():
    fc = await _first_tool(f"Unban user id {_USER_ID}")
    assert fc is not None
    assert fc.name == "manage_server"
    assert fc.args.get("action") == "unban"
    assert fc.args.get("user_id") == _USER_ID


async def test_timeout_selected():
    fc = await _first_tool(f"Timeout user id {_USER_ID} for 30 minutes")
    assert fc is not None
    assert fc.name == "manage_server"
    assert fc.args.get("action") == "timeout"
    assert fc.args.get("user_id") == _USER_ID
    assert int(fc.args.get("duration_minutes", 0)) == 30


async def test_remove_timeout_selected():
    fc = await _first_tool(f"Remove the timeout from user id {_USER_ID}")
    assert fc is not None
    assert fc.name == "manage_server"
    assert fc.args.get("action") == "remove_timeout"
    assert fc.args.get("user_id") == _USER_ID


async def test_create_channel_selected():
    fc = await _first_tool("Create a new text channel called dev-chat")
    assert fc is not None
    assert fc.name == "manage_server"
    assert fc.args.get("action") == "create_channel"
    assert "dev" in fc.args.get("new_name", "").lower()


async def test_create_voice_channel_type():
    fc = await _first_tool("Create a new voice channel called Gaming")
    assert fc is not None
    assert fc.name == "manage_server"
    assert fc.args.get("action") == "create_channel"
    assert fc.args.get("channel_type") == "voice"


async def test_delete_channel_selected():
    fc = await _first_tool("Delete the #general channel")
    assert fc is not None
    assert fc.name == "manage_server"
    assert fc.args.get("action") == "delete_channel"
    assert fc.args.get("channel_id") == "333333333333333333"


async def test_rename_channel_selected():
    fc = await _first_tool("Rename #general to general-chat")
    assert fc is not None
    assert fc.name == "manage_server"
    assert fc.args.get("action") == "rename_channel"
    assert fc.args.get("channel_id") == "333333333333333333"
    assert "general-chat" in fc.args.get("new_name", "").lower()


# ---------------------------------------------------------------------------
# get_bot_commands
# ---------------------------------------------------------------------------

async def test_get_bot_commands_all_selected():
    fc = await _first_tool("What slash commands do all the bots in this server have?")
    assert fc is not None
    assert fc.name == "get_bot_commands"
    assert fc.args.get("bot") == "all"


async def test_get_bot_commands_specific_bot_by_name():
    fc = await _first_tool("What commands does MEE6 have?")
    assert fc is not None
    assert fc.name == "get_bot_commands"
    assert "mee6" in fc.args.get("bot", "").lower()


async def test_get_bot_commands_not_scan_bots():
    fc = await _first_tool("List all the slash commands available from server bots")
    assert fc is not None
    assert fc.name == "get_bot_commands"
