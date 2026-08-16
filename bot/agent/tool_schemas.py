"""Gemini function declarations for all Phase 1 read-only tools.

Each FunctionDeclaration maps 1-to-1 to a function in bot/tools/.
The orchestrator passes TOOL_SCHEMAS to every Gemini chat session so the
model can invoke tools by name.

ID parameters (channel_id, author_id) are typed STRING rather than INTEGER
because Discord snowflakes exceed JavaScript's safe integer range and would
lose precision if serialised as JSON floats.
"""

from datetime import datetime, timezone

from google.genai import types

from bot.tools.media import find_media
from bot.tools.search import find_message_by_context, search_messages
from bot.tools.summarize import summarize_channel

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
# Exported schemas
# ---------------------------------------------------------------------------

PHASE1_TOOLS = types.Tool(
    function_declarations=[
        _search_messages,
        _find_message_by_context,
        _summarize_channel,
        _find_media,
    ]
)

# TOOL_SCHEMAS is the list passed to the Gemini client on every chat session.
# Extend this list as phases are implemented.
TOOL_SCHEMAS: list[types.Tool] = [PHASE1_TOOLS]

# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def dispatch(tool_name: str, args: dict) -> object:
    """Execute a tool by name with the arguments Gemini provided.

    Handles type coercion (string IDs → int, ISO datetime strings → datetime)
    so individual tool functions stay clean.
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

    match tool_name:
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
        case _:
            raise ValueError(f"Unknown tool: {tool_name}")
