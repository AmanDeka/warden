"""Gemini function declarations for all Phase 1 read-only tools.

Each FunctionDeclaration maps 1-to-1 to a function in bot/tools/.
The orchestrator passes TOOL_SCHEMAS to every Gemini chat session so the
model can invoke tools by name.

ID parameters (channel_id, author_id) are typed STRING rather than INTEGER
because Discord snowflakes exceed JavaScript's safe integer range and would
lose precision if serialised as JSON floats.
"""

from datetime import datetime, timezone

import discord
from google.genai import types

from bot.tools.audit import _AUDIT_ACTIONS, bulk_permission_audit, get_audit_log
from bot.tools.media import find_media
from bot.tools.permissions import (
    assign_role,
    create_role,
    delete_role,
    fix_bot_access,
    get_member_roles,
    list_permissions,
    list_roles,
    remove_role,
    scan_bots,
    set_channel_permission,
)
from bot.tools.moderation import ACTIONS as _MODERATION_ACTIONS, manage_server
from bot.tools.reminders import delete_reminder, list_reminders, set_reminder
from bot.tools.search import find_message_by_context, search_messages
from bot.tools.summarize import summarize_channel

_AUDIT_ACTIONS_ENUM = list(_AUDIT_ACTIONS.keys())

# ---------------------------------------------------------------------------
# search_messages
# ---------------------------------------------------------------------------

_search_messages = types.FunctionDeclaration(
    name="search_messages",
    description=(
        "Search the message index for a channel by keyword or phrase. "
        "Uses FTS or semantic search depending on the current server setting. "
        "Use this when the user wants to find specific messages by content."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "channel_id": types.Schema(
                type=types.Type.STRING,
                description="Discord channel ID to search in.",
            ),
            "query": types.Schema(
                type=types.Type.STRING,
                description="Keyword, phrase, or natural-language query to search for.",
            ),
            "author_id": types.Schema(
                type=types.Type.STRING,
                description="Optional. Filter results to messages sent by this user ID.",
            ),
            "limit": types.Schema(
                type=types.Type.INTEGER,
                description="Maximum number of results to return. Defaults to 50.",
            ),
        },
        required=["channel_id", "query"],
    ),
)

# ---------------------------------------------------------------------------
# find_message_by_context
# ---------------------------------------------------------------------------

_find_message_by_context = types.FunctionDeclaration(
    name="find_message_by_context",
    description=(
        "Find a specific message using a natural-language description of what you remember about it "
        "(e.g. 'the message where someone complained about the deploy'). "
        "Uses semantic similarity — always prefer this over search_messages when the user is "
        "describing a message rather than searching for an exact keyword."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "channel_id": types.Schema(
                type=types.Type.STRING,
                description="Discord channel ID to search in.",
            ),
            "description": types.Schema(
                type=types.Type.STRING,
                description="Natural-language description of the message to find.",
            ),
        },
        required=["channel_id", "description"],
    ),
)

# ---------------------------------------------------------------------------
# summarize_channel
# ---------------------------------------------------------------------------

_summarize_channel = types.FunctionDeclaration(
    name="summarize_channel",
    description=(
        "Fetch recent messages from a channel so you can summarize them. "
        "Returns raw messages with author IDs and timestamps — your summary must cite "
        "authors and timestamps, not just paraphrase generically. "
        "Use the `since` parameter to limit to a specific time window."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "channel_id": types.Schema(
                type=types.Type.STRING,
                description="Discord channel ID to summarize.",
            ),
            "since": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Optional ISO 8601 datetime. Only include messages after this point "
                    "(e.g. '2024-01-15T00:00:00Z'). Omit to fetch the most recent messages."
                ),
            ),
            "limit": types.Schema(
                type=types.Type.INTEGER,
                description="Maximum number of messages to fetch. Defaults to 200.",
            ),
        },
        required=["channel_id"],
    ),
)

# ---------------------------------------------------------------------------
# find_media
# ---------------------------------------------------------------------------

_find_media = types.FunctionDeclaration(
    name="find_media",
    description=(
        "Find messages in a channel that contain file attachments of a given type. "
        "Optionally filter by a keyword in the message content."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "channel_id": types.Schema(
                type=types.Type.STRING,
                description="Discord channel ID to search in.",
            ),
            "media_type": types.Schema(
                type=types.Type.STRING,
                enum=["image", "video", "audio", "file"],
                description=(
                    "Type of attachment to look for. "
                    "'file' matches any attachment regardless of type. "
                    "Defaults to 'image'."
                ),
            ),
            "query": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Optional keyword to filter by message content "
                    "(e.g. 'logo' to find messages that mention logo and contain an image)."
                ),
            ),
            "limit": types.Schema(
                type=types.Type.INTEGER,
                description="Maximum number of results to return. Defaults to 200.",
            ),
        },
        required=["channel_id"],
    ),
)

# ---------------------------------------------------------------------------
# list_permissions
# ---------------------------------------------------------------------------

_list_permissions = types.FunctionDeclaration(
    name="list_permissions",
    description=(
        "Show the permission overwrites for a channel, or the full permission set for a role. "
        "Pass a channel ID to see who has custom overwrites in that channel. "
        "Pass a role ID to see what permissions that role has server-wide."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "target_id": types.Schema(
                type=types.Type.STRING,
                description="ID of the channel or role to inspect.",
            ),
        },
        required=["target_id"],
    ),
)

# ---------------------------------------------------------------------------
# list_roles
# ---------------------------------------------------------------------------

_list_roles = types.FunctionDeclaration(
    name="list_roles",
    description="List all roles in the server with their permissions, position, and member count.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={},
    ),
)

# ---------------------------------------------------------------------------
# get_member_roles
# ---------------------------------------------------------------------------

_get_member_roles = types.FunctionDeclaration(
    name="get_member_roles",
    description="Get the roles assigned to a specific server member.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_id": types.Schema(
                type=types.Type.STRING,
                description="Discord user ID of the member to look up.",
            ),
        },
        required=["user_id"],
    ),
)

# ---------------------------------------------------------------------------
# get_audit_log
# ---------------------------------------------------------------------------

_get_audit_log = types.FunctionDeclaration(
    name="get_audit_log",
    description=(
        "Fetch recent server audit log entries. "
        "Shows who did what and when — useful for reviewing recent moderation actions, "
        "role changes, permission changes, or bans."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "action_type": types.Schema(
                type=types.Type.STRING,
                enum=list(_AUDIT_ACTIONS_ENUM),
                description="Optional. Filter to a specific action type.",
            ),
            "limit": types.Schema(
                type=types.Type.INTEGER,
                description="Number of entries to fetch. Defaults to 20.",
            ),
        },
    ),
)

# ---------------------------------------------------------------------------
# bulk_permission_audit
# ---------------------------------------------------------------------------

_bulk_permission_audit = types.FunctionDeclaration(
    name="bulk_permission_audit",
    description=(
        "Scan every channel in the server and flag permission anomalies: "
        "orphaned overwrites for deleted roles/users, @everyone granted dangerous permissions, "
        "and channels that are completely inaccessible to everyone."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={},
    ),
)

# ---------------------------------------------------------------------------
# assign_role
# ---------------------------------------------------------------------------

_assign_role = types.FunctionDeclaration(
    name="assign_role",
    description="Add a role to a server member. Requires confirmation.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_id": types.Schema(type=types.Type.STRING, description="Discord user ID of the member."),
            "role_id": types.Schema(type=types.Type.STRING, description="Discord role ID to assign."),
        },
        required=["user_id", "role_id"],
    ),
)

# ---------------------------------------------------------------------------
# remove_role
# ---------------------------------------------------------------------------

_remove_role = types.FunctionDeclaration(
    name="remove_role",
    description="Remove a role from a server member. Requires confirmation.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_id": types.Schema(type=types.Type.STRING, description="Discord user ID of the member."),
            "role_id": types.Schema(type=types.Type.STRING, description="Discord role ID to remove."),
        },
        required=["user_id", "role_id"],
    ),
)

# ---------------------------------------------------------------------------
# set_channel_permission
# ---------------------------------------------------------------------------

_set_channel_permission = types.FunctionDeclaration(
    name="set_channel_permission",
    description=(
        "Set a permission overwrite for a role or member on a specific channel. "
        "Use discord.py permission names (snake_case): view_channel, send_messages, "
        "read_message_history, embed_links, manage_messages, etc. Requires confirmation."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "channel_id": types.Schema(type=types.Type.STRING, description="Channel to modify."),
            "target_id": types.Schema(type=types.Type.STRING, description="Role or member ID to set the overwrite for."),
            "allow": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="Permission names to explicitly allow.",
            ),
            "deny": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="Permission names to explicitly deny.",
            ),
        },
        required=["channel_id", "target_id"],
    ),
)

# ---------------------------------------------------------------------------
# create_role
# ---------------------------------------------------------------------------

_create_role = types.FunctionDeclaration(
    name="create_role",
    description="Create a new server role. Requires confirmation.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "name": types.Schema(type=types.Type.STRING, description="Name for the new role."),
            "permissions": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="List of discord.py permission names to grant (snake_case). Omit for no permissions.",
            ),
            "color": types.Schema(
                type=types.Type.STRING,
                description="Hex color code for the role, e.g. #ff0000. Omit for default.",
            ),
        },
        required=["name"],
    ),
)

# ---------------------------------------------------------------------------
# delete_role
# ---------------------------------------------------------------------------

_delete_role = types.FunctionDeclaration(
    name="delete_role",
    description="Permanently delete a server role. Requires confirmation.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "role_id": types.Schema(type=types.Type.STRING, description="ID of the role to delete."),
        },
        required=["role_id"],
    ),
)

# ---------------------------------------------------------------------------
# manage_server
# ---------------------------------------------------------------------------

_manage_server = types.FunctionDeclaration(
    name="manage_server",
    description=(
        "Unified moderation and channel management tool. "
        "Choose an action and supply the relevant arguments for it:\n"
        "- kick: user_id, reason?\n"
        "- ban: user_id, reason?, delete_message_days?\n"
        "- unban: user_id, reason?\n"
        "- timeout: user_id, duration_minutes, reason?\n"
        "- remove_timeout: user_id, reason?\n"
        "- create_channel: new_name, channel_type? (text/voice/forum), category_id?\n"
        "- delete_channel: channel_id, reason?\n"
        "- rename_channel: channel_id, new_name\n"
        "- move_member: user_id, voice_channel_id\n"
        "All actions require confirmation and the user must be on the permissions allowlist."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "action": types.Schema(
                type=types.Type.STRING,
                enum=list(_MODERATION_ACTIONS.keys()),
                description="The action to perform.",
            ),
            "user_id": types.Schema(type=types.Type.STRING, description="Target member's Discord user ID."),
            "channel_id": types.Schema(type=types.Type.STRING, description="Target channel ID (for channel actions)."),
            "voice_channel_id": types.Schema(type=types.Type.STRING, description="Destination voice channel ID (for move_member)."),
            "new_name": types.Schema(type=types.Type.STRING, description="Channel name (for create_channel or rename_channel)."),
            "channel_type": types.Schema(
                type=types.Type.STRING,
                enum=["text", "voice", "forum"],
                description="Channel type for create_channel. Defaults to 'text'.",
            ),
            "category_id": types.Schema(type=types.Type.STRING, description="Category channel ID to place a new channel under."),
            "reason": types.Schema(type=types.Type.STRING, description="Optional audit log reason."),
            "duration_minutes": types.Schema(type=types.Type.INTEGER, description="Timeout duration in minutes (for timeout action)."),
            "delete_message_days": types.Schema(type=types.Type.INTEGER, description="Days of messages to delete on ban (0–7). Defaults to 0."),
        },
        required=["action"],
    ),
)

# ---------------------------------------------------------------------------
# set_reminder
# ---------------------------------------------------------------------------

_set_reminder = types.FunctionDeclaration(
    name="set_reminder",
    description=(
        "Create a reminder or birthday reminder that will ping a user at a future date. "
        "For general reminders: provide remind_at as an ISO 8601 UTC datetime. "
        "For birthdays: set category='birthday', provide birthday_month and birthday_day, "
        "set tag to the person's name, and omit remind_at (it is calculated automatically). "
        "Supply created_by and target_user_id from the requesting user's ID in the server context. "
        "Supply channel_id as the channel the user is currently speaking in."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "created_by": types.Schema(type=types.Type.STRING, description="User ID of the person setting the reminder."),
            "target_user_id": types.Schema(type=types.Type.STRING, description="User ID to ping when the reminder fires. Usually the same as created_by."),
            "message": types.Schema(type=types.Type.STRING, description="The reminder text to deliver."),
            "channel_id": types.Schema(type=types.Type.STRING, description="Channel ID where the reminder will be posted."),
            "remind_at": types.Schema(type=types.Type.STRING, description="ISO 8601 UTC datetime when the reminder fires (e.g. '2026-09-01T09:00:00Z'). Required for general reminders; omit for birthdays."),
            "repeat": types.Schema(
                type=types.Type.STRING,
                enum=["daily", "weekly", "monthly", "yearly"],
                description="Optional repeat interval. Omit for a one-time reminder. Defaults to 'yearly' when category='birthday'.",
            ),
            "category": types.Schema(
                type=types.Type.STRING,
                enum=["general", "birthday"],
                description="'birthday' for yearly birthday reminders, 'general' (default) for everything else.",
            ),
            "tag": types.Schema(type=types.Type.STRING, description="For birthdays: the person's name. Used as a label in reminder listings."),
            "birthday_month": types.Schema(type=types.Type.INTEGER, description="Birth month (1–12). Required when category='birthday'."),
            "birthday_day": types.Schema(type=types.Type.INTEGER, description="Birth day (1–31). Required when category='birthday'."),
        },
        required=["created_by", "target_user_id", "message", "channel_id"],
    ),
)

# ---------------------------------------------------------------------------
# list_reminders
# ---------------------------------------------------------------------------

_list_reminders = types.FunctionDeclaration(
    name="list_reminders",
    description="List all active reminders (including birthdays) created by a user.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "user_id": types.Schema(type=types.Type.STRING, description="Discord user ID whose reminders to list."),
        },
        required=["user_id"],
    ),
)

# ---------------------------------------------------------------------------
# delete_reminder
# ---------------------------------------------------------------------------

_delete_reminder = types.FunctionDeclaration(
    name="delete_reminder",
    description="Cancel an active reminder by its ID. Only the creator can cancel it.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "reminder_id": types.Schema(type=types.Type.INTEGER, description="The numeric ID of the reminder to cancel."),
            "user_id": types.Schema(type=types.Type.STRING, description="User ID of the requester (must be the reminder's creator)."),
        },
        required=["reminder_id", "user_id"],
    ),
)

# ---------------------------------------------------------------------------
# scan_bots
# ---------------------------------------------------------------------------

_scan_bots = types.FunctionDeclaration(
    name="scan_bots",
    description=(
        "List all bots in the server with their roles and any dangerous permissions they hold "
        "(administrator, manage_roles, ban_members, etc.). "
        "Use this to audit which bots are present and whether any are over-privileged."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={},
    ),
)

# ---------------------------------------------------------------------------
# fix_bot_access
# ---------------------------------------------------------------------------

_fix_bot_access = types.FunctionDeclaration(
    name="fix_bot_access",
    description=(
        "Diagnose why another bot can't operate in a channel. "
        "Walks the permission stack (server roles → category → channel overwrite), "
        "identifies which required permissions are missing, and proposes a minimal overwrite fix. "
        "Does not apply the fix — use set_channel_permission with the proposed args to do that."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "channel_id": types.Schema(type=types.Type.STRING, description="Channel to diagnose."),
            "bot_name_or_id": types.Schema(
                type=types.Type.STRING,
                description="The other bot's display name or Discord user ID.",
            ),
        },
        required=["channel_id", "bot_name_or_id"],
    ),
)

# ---------------------------------------------------------------------------
# Exported schemas
# ---------------------------------------------------------------------------

TOOLS = types.Tool(
    function_declarations=[
        # Phase 1 — read-only index tools
        _search_messages,
        _find_message_by_context,
        _summarize_channel,
        _find_media,
        # Phase 2 — permission introspection
        _list_permissions,
        _list_roles,
        _get_member_roles,
        _get_audit_log,
        _bulk_permission_audit,
        # Moderation & channel management
        _manage_server,
        # Reminders & birthdays
        _set_reminder,
        _list_reminders,
        _delete_reminder,
        # Phase 2.5 — bot scanner
        _scan_bots,
        # Phase 3 — guarded write tools
        _assign_role,
        _remove_role,
        _set_channel_permission,
        _create_role,
        _delete_role,
        _fix_bot_access,
    ]
)

TOOL_SCHEMAS: list[types.Tool] = [TOOLS]

# ---------------------------------------------------------------------------
# Write-tool registry
# ---------------------------------------------------------------------------

TOOL_LABELS: dict[str, str] = {
    "search_messages":          "Searching messages",
    "find_message_by_context":  "Finding message by description",
    "summarize_channel":        "Fetching messages to summarize",
    "find_media":               "Searching for media",
    "list_permissions":         "Checking permissions",
    "list_roles":               "Listing roles",
    "get_member_roles":         "Getting member's roles",
    "get_audit_log":            "Reading audit log",
    "bulk_permission_audit":    "Scanning all channels for permission issues",
    "scan_bots":                "Scanning bots in the server",
    "manage_server":            "Server action",
    "set_reminder":             "Setting reminder",
    "list_reminders":           "Listing reminders",
    "delete_reminder":          "Cancelling reminder",
    "assign_role":              "Assigning role",
    "remove_role":              "Removing role",
    "set_channel_permission":   "Setting channel permission",
    "clean_permissions":        "Cleaning permissions",
    "create_role":              "Creating role",
    "delete_role":              "Deleting role",
    "fix_bot_access":           "Diagnosing bot access",
}

WRITE_TOOLS: frozenset[str] = frozenset({
    "assign_role",
    "remove_role",
    "set_channel_permission",
    "clean_permissions",
    "create_role",
    "delete_role",
    "manage_server",
})


def describe_write_action(tool_name: str, args: dict, guild: discord.Guild | None) -> str:
    """Return a plain-English one-liner (or short block) describing what the tool will do.

    Used to populate the confirmation embed before execution.
    Resolves IDs to names where the guild cache allows.
    """
    def _role(key: str) -> str:
        val = args.get(key)
        if val is None:
            return "?"
        if guild:
            r = guild.get_role(int(val))
            if r:
                return f"@{r.name}"
        return f"role {val}"

    def _channel(key: str) -> str:
        val = args.get(key)
        if val is None:
            return "?"
        if guild:
            ch = guild.get_channel(int(val))
            if ch:
                return f"#{ch.name}"
        return f"channel {val}"

    def _member(key: str) -> str:
        val = args.get(key)
        if val is None:
            return "?"
        if guild:
            m = guild.get_member(int(val))
            if m:
                return m.display_name
        return f"user {val}"

    def _target(key: str) -> str:
        """Resolve a target_id that could be either a role or a member."""
        val = args.get(key)
        if val is None:
            return "?"
        if guild:
            r = guild.get_role(int(val))
            if r:
                return f"@{r.name}"
            m = guild.get_member(int(val))
            if m:
                return m.display_name
        return f"target {val}"

    match tool_name:
        case "assign_role":
            return f"Assign {_role('role_id')} → {_member('user_id')}"
        case "remove_role":
            return f"Remove {_role('role_id')} from {_member('user_id')}"
        case "set_channel_permission":
            allow = ", ".join(args.get("allow", [])) or "none"
            deny = ", ".join(args.get("deny", [])) or "none"
            return (
                f"Set overwrite on {_channel('channel_id')} for {_target('target_id')}\n"
                f"  Allow: {allow}\n"
                f"  Deny: {deny}"
            )
        case "clean_permissions":
            policy = args.get("policy", "sync_to_category")
            return f"Clean permissions on {_channel('channel_id')} — policy: `{policy}`"
        case "create_role":
            perms = ", ".join(args.get("permissions", [])) or "none"
            return f"Create role **{args.get('name', '?')}** — permissions: {perms}"
        case "delete_role":
            return f"Delete {_role('role_id')}"
        case "fix_bot_access":
            return (
                f"Fix bot access in {_channel('channel_id')} "
                f"for bot: {args.get('bot_name_or_id', '?')}"
            )
        case "manage_server":
            action = args.get("action", "?")
            reason = args.get("reason")
            suffix = f" — reason: {reason}" if reason else ""
            match action:
                case "kick":
                    return f"Kick {_member('user_id')}{suffix}"
                case "ban":
                    days = args.get("delete_message_days", 0)
                    return f"Ban {_member('user_id')} (delete {days}d of messages){suffix}"
                case "unban":
                    return f"Unban user {args.get('user_id', '?')}{suffix}"
                case "timeout":
                    mins = args.get("duration_minutes", "?")
                    return f"Timeout {_member('user_id')} for {mins} minutes{suffix}"
                case "remove_timeout":
                    return f"Remove timeout from {_member('user_id')}{suffix}"
                case "create_channel":
                    ctype = args.get("channel_type", "text")
                    return f"Create {ctype} channel **#{args.get('new_name', '?')}**{suffix}"
                case "delete_channel":
                    return f"Delete {_channel('channel_id')}{suffix}"
                case "rename_channel":
                    return f"Rename {_channel('channel_id')} → **#{args.get('new_name', '?')}**{suffix}"
                case "move_member":
                    vc_id = args.get("voice_channel_id")
                    vc_label = f"<#{vc_id}>" if vc_id else "?"
                    return f"Move {_member('user_id')} to voice channel {vc_label}{suffix}"
                case _:
                    return f"manage_server action={action} args={args}"
        case _:
            return f"`{tool_name}` with args: {args}"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def dispatch(
    tool_name: str,
    args: dict,
    guild: discord.Guild | None = None,
) -> object:
    """Execute a tool by name with the arguments Gemini provided.

    Handles type coercion (string IDs → int, ISO datetime strings → datetime)
    so individual tool functions stay clean.
    Guild-dependent tools raise if guild is None (should never happen for server messages).
    """
    def _int(key: str, default: int | None = None) -> int | None:
        val = args.get(key, default)
        return int(val) if val is not None else default

    def _dt(key: str) -> datetime | None:
        val = args.get(key)
        if val is None:
            return None
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _guild() -> discord.Guild:
        if guild is None:
            raise ValueError("This tool requires a server context and cannot be used in DMs.")
        return guild

    match tool_name:
        # Phase 1 — read-only index tools
        case "search_messages":
            return await search_messages(
                channel_id=int(args["channel_id"]),
                query=args["query"],
                author_id=_int("author_id"),
                limit=_int("limit", 50),
            )
        case "find_message_by_context":
            return await find_message_by_context(
                channel_id=int(args["channel_id"]),
                description=args["description"],
            )
        case "summarize_channel":
            return await summarize_channel(
                channel_id=int(args["channel_id"]),
                since=_dt("since"),
                limit=_int("limit", 200),
            )
        case "find_media":
            return await find_media(
                channel_id=int(args["channel_id"]),
                media_type=args.get("media_type", "image"),
                query=args.get("query"),
                limit=_int("limit", 200),
            )
        # Phase 2 — permission introspection tools
        case "list_permissions":
            return await list_permissions(_guild(), int(args["target_id"]))
        case "list_roles":
            return await list_roles(_guild())
        case "get_member_roles":
            return await get_member_roles(_guild(), int(args["user_id"]))
        case "get_audit_log":
            return await get_audit_log(
                _guild(),
                action_type=args.get("action_type"),
                limit=_int("limit", 20),
            )
        case "bulk_permission_audit":
            return await bulk_permission_audit(_guild())
        case "scan_bots":
            return await scan_bots(_guild())
        # Reminders & birthdays
        case "set_reminder":
            return await set_reminder(
                guild_id=_guild().id,
                created_by=int(args["created_by"]),
                target_user_id=int(args["target_user_id"]),
                message=args["message"],
                channel_id=int(args["channel_id"]),
                remind_at=_dt("remind_at"),
                repeat=args.get("repeat"),
                category=args.get("category", "general"),
                tag=args.get("tag"),
                birthday_month=_int("birthday_month"),
                birthday_day=_int("birthday_day"),
            )
        case "list_reminders":
            return await list_reminders(guild_id=_guild().id, user_id=int(args["user_id"]))
        case "delete_reminder":
            return await delete_reminder(
                reminder_id=int(args["reminder_id"]),
                user_id=int(args["user_id"]),
            )
        # Moderation & channel management
        case "manage_server":
            return await manage_server(
                _guild(),
                action=args["action"],
                user_id=_int("user_id"),
                reason=args.get("reason"),
                delete_message_days=int(args.get("delete_message_days") or 0),
                duration_minutes=_int("duration_minutes"),
                channel_id=_int("channel_id"),
                new_name=args.get("new_name"),
                channel_type=args.get("channel_type", "text"),
                category_id=_int("category_id"),
                voice_channel_id=_int("voice_channel_id"),
            )
        # Phase 3 — guarded write tools
        case "assign_role":
            return await assign_role(_guild(), int(args["user_id"]), int(args["role_id"]))
        case "remove_role":
            return await remove_role(_guild(), int(args["user_id"]), int(args["role_id"]))
        case "set_channel_permission":
            return await set_channel_permission(
                _guild(),
                channel_id=int(args["channel_id"]),
                target_id=int(args["target_id"]),
                allow=list(args.get("allow") or []),
                deny=list(args.get("deny") or []),
            )
        case "create_role":
            return await create_role(
                _guild(),
                name=args["name"],
                permissions=list(args.get("permissions") or []),
                color=args.get("color"),
            )
        case "delete_role":
            return await delete_role(_guild(), int(args["role_id"]))
        case "fix_bot_access":
            return await fix_bot_access(
                _guild(),
                channel_id=int(args["channel_id"]),
                bot_name_or_id=args["bot_name_or_id"],
            )
        case _:
            raise ValueError(f"Unknown tool: {tool_name}")
