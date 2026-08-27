# Warden

An agentic Discord bot that understands natural language. Instead of fixed slash commands, you talk to it — it uses **Gemini function calling** to decide which actions to run: searching messages, summarizing channels, finding media, or managing roles and permissions.

---

## How it works

```
@mention / reply / DM
        │
        ▼
Gateway Listener (discord.py)
        │
        ▼
Agent Orchestrator ──► Gemini API (function calling loop, max 5 iterations)
        │
        ▼
Tool Executor ──► Discord REST API
        │
        ▼
Guardrail Layer (confirmation for write actions)
        │
        ▼
Response formatter ──► Status embed + Final answer embed
        │
        ▼
Conversation store (per-user, cross-channel)
        │
        ▼
Audit log
```

Gemini is the brain. Python + discord.py are the hands.

---

## Talking to the bot

| Trigger | How |
|---|---|
| `@Warden <question>` | Mention it in any channel |
| Reply to a bot message | Continues the conversation without re-mentioning |
| DM the bot | No mention needed |
| `/ask <question>` | Slash command alternative |

Conversation memory is keyed **per user across all channels** — asking something in `#general` and following up in `#dev-chat` an hour later gives full continuity.

---

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Discord library | discord.py 2.x |
| LLM | Gemini API (`google-genai` SDK) |
| Embeddings | Gemini `text-embedding-004` |
| Storage | SQLite with FTS5 |
| Package manager | uv |
| Secrets | `.env` via `python-dotenv` |

---

## Setup

### 1. Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- A Gemini API key ([Google AI Studio](https://aistudio.google.com))

### 2. Enable bot intents

In the Discord Developer Portal → your app → **Bot** tab, enable:
- `MESSAGE CONTENT INTENT`
- `SERVER MEMBERS INTENT`

### 3. Bot permissions

When inviting the bot, grant:
- View Channels, Read Message History, Send Messages, Embed Links, Add Reactions, View Audit Log
- Manage Roles, Manage Channels *(required for Phase 3 write tools)*

### 4. Install

```bash
uv sync
```

### 5. Configure

```bash
cp .env.example .env
```

Fill in `.env`:

```env
DISCORD_TOKEN=your_discord_bot_token
GEMINI_API_KEY=your_gemini_api_key
GUILD_ID=your_discord_server_id
```

### 6. Run

```bash
uv run warden
```

On first startup the bot will:
1. Initialize the SQLite database
2. Register slash commands with your server
3. Begin backfilling message history for all channels in the background

---

## Current implementation

### Message indexer

A background component with no LLM involvement. Keeps a local SQLite index of all messages in real time.

- **`on_message`** — writes message content, attachments, and embeds to the index immediately
- **`on_message_edit`** — updates stored content, keeps the FTS index in sync
- **`on_message_delete`** — soft-deletes (marks `deleted_at`); excluded from search but retained for audit purposes
- **`on_raw_message_delete`** — handles deletes for messages not in discord.py's local cache
- **Backfill** — on startup, paginates full channel history for all text channels with throttling
- **Embeddings** — every new or edited message generates a Gemini embedding as a fire-and-forget background task

### Tools

#### `search_messages(channel_id, query, author_id?, limit?)`

Searches the message index. Two backends, switchable at runtime via `/search-mode`:

| Backend | How | Cost |
|---|---|---|
| FTS (default) | SQLite FTS5 phrase match | Free |
| Semantic | Gemini `text-embedding-004` cosine similarity | Per-query API call |

Switching is instant — embeddings are always generated regardless of current mode, so no re-indexing is needed.

#### `find_message_by_context(channel_id, description)`

Finds a specific message by natural-language description. Always uses semantic search, falls back to FTS when embeddings aren't available yet.

#### `summarize_channel(channel_id, since?, limit?)`

Fetches up to `limit` messages from the index (oldest-first, optional date filter). Gemini writes the summary from the raw messages in its final response.

#### `find_media(channel_id, media_type?, query?, limit?)`

Finds messages containing attachments of a given type (`image`, `video`, `audio`, `file`). Optional keyword filter on message content.

#### `list_permissions(target_id)`

Pass a channel ID to see its permission overwrites. Pass a role ID to see its server-wide permissions.

#### `list_roles()`

All roles in the server sorted by position, with permissions and member count.

#### `get_member_roles(user_id)`

Roles held by a specific server member.

#### `get_audit_log(action_type?, limit?)`

Recent audit log entries — who did what and when. Filterable by action type (ban, kick, role_create, channel_update, etc.).

#### `bulk_permission_audit()`

Scans every channel and flags:
- Orphaned overwrites for deleted roles/users
- `@everyone` granted dangerous permissions in a channel
- Channels completely inaccessible to everyone

### Write tools (Phase 3)

All write tools require the requesting user to hold a role on the [permissions allowlist](#permissions-allowlist). Before executing, Warden shows the proposed change in the status box and waits for a ✅/❌ reaction. Cancelling or ignoring (60s timeout) aborts the action.

#### `assign_role(user_id, role_id)`

Adds a role to a server member. Warden's own role must sit above the target role in the hierarchy or Discord will reject it.

#### `remove_role(user_id, role_id)`

Removes a role from a server member. Same hierarchy constraint as `assign_role`.

#### `set_channel_permission(channel_id, target_id, allow, deny)`

Sets a permission overwrite on a channel for a role or member. `allow` and `deny` are lists of discord.py permission names in snake_case (e.g. `view_channel`, `send_messages`, `read_message_history`). Either list can be empty.

#### `create_role(name, permissions?, color?)`

Creates a new server role. `permissions` is an optional list of snake_case permission names. `color` is an optional hex string (e.g. `#ff0000`).

#### `delete_role(role_id)`

Permanently deletes a role. Refuses to delete integration-managed roles.

#### `fix_bot_access(channel_id, bot_name_or_id)`

Diagnoses why another bot can't operate in a channel. Resolves the bot by display name or user ID, walks the full permission stack (server roles → category overwrite → channel overwrite), and identifies which required permissions are missing and why. Returns a ready-to-use `set_channel_permission` call as the proposed fix — does not apply it automatically.

#### `manage_server(action, ...)`

Unified moderation and channel management tool. Choose an action and supply the relevant arguments:

| Action | Required | Optional |
|---|---|---|
| `kick` | `user_id` | `reason` |
| `ban` | `user_id` | `reason`, `delete_message_days` (0–7, default 0) |
| `unban` | `user_id` | `reason` |
| `timeout` | `user_id`, `duration_minutes` | `reason` |
| `remove_timeout` | `user_id` | `reason` |
| `create_channel` | `new_name` | `channel_type` (text/voice/forum), `category_id`, `reason` |
| `delete_channel` | `channel_id` | `reason` |
| `rename_channel` | `channel_id`, `new_name` | `reason` |
| `move_member` | `user_id`, `voice_channel_id` | — |

All actions require confirmation and the requesting user must be on the permissions allowlist.

#### `scan_bots()`

Lists all bots in the server with their roles and flags any holding dangerous permissions (`administrator`, `manage_roles`, `ban_members`, `kick_members`, `manage_guild`, etc.). Useful for auditing over-privileged integrations. Read-only — no confirmation required.

### Reminders & calendar

Reminders are stored in SQLite and survive bot restarts. A background task checks every minute and delivers any due reminders by pinging the target user in the configured channel.

#### `set_reminder(created_by, target_user_id, message, channel_id, remind_at?, repeat?, category?, tag?, birthday_month?, birthday_day?)`

Creates a reminder. For general reminders, provide `remind_at` as an ISO 8601 UTC datetime. `repeat` accepts `daily`, `weekly`, `monthly`, or `yearly`. Missed reminders (e.g. bot was offline) are delivered on the next tick after restart rather than silently skipped.

Birthdays are a subcategory of this same tool — set `category='birthday'`, provide `birthday_month` and `birthday_day`, and set `tag` to the person's name. `remind_at` is calculated automatically and the reminder repeats yearly. No separate birthday tool needed.

#### `list_reminders(user_id)`

Shows all active reminders (including birthdays) created by a user, sorted by next fire time.

#### `delete_reminder(reminder_id, user_id)`

Cancels an active reminder by ID. Only the creator can cancel it.

### Storage

| Table | Purpose |
|---|---|
| `messages` | Full message index (content, attachments, embeds, soft-delete) |
| `messages_fts` | FTS5 virtual table over `messages.content` |
| `message_embeddings` | Gemini embedding vectors per message |
| `conversation_context` | Per-user conversation history (cross-channel) |
| `audit_log` | Every tool call: who ran what, with what args, and what happened |
| `permission_allowlist` | Roles authorised to use write/permission tools |
| `indexed_channels` | Whitelist of channels the indexer watches (empty = all channels) |
| `settings` | Runtime key/value config (e.g. `search_method`) |
| `reminders` | Active and completed reminders (one-time and repeating) |

### Channel index whitelist

By default Warden indexes all channels. Once any channel is added to the whitelist, only whitelisted channels are indexed for new messages, edits, and backfills. The whitelist persists across restarts (stored in SQLite) and is cached in memory so there is no DB hit on every message.

### Permissions allowlist

Write tools (Phase 3) require the requesting user to hold a role on an explicit owner-configured allowlist — Discord's own `Manage Roles` permission is not sufficient on its own. This prevents scope creep where "can manage permissions manually" silently becomes "can direct the bot to manage permissions."

The allowlist is stored in the `permission_allowlist` table and cached in memory so there is no DB hit on every tool invocation. It is managed via `/permissions-allowlist` (owner/admin only). The allowlist starts empty — no one can invoke write tools until a role is explicitly added.

### Slash commands

| Command | Who | What |
|---|---|---|
| `/ask <question>` | Everyone | Ask Warden something directly |
| `/search-mode [fts\|semantic]` | Admins | Switch the search backend |
| `/index-channels list` | Admins | Show which channels are currently being indexed |
| `/index-channels add #channel` | Admins | Add a channel to the whitelist and backfill its history |
| `/index-channels remove #channel` | Admins | Remove a channel from the whitelist (existing data kept) |
| `/permissions-allowlist list` | Owner / Admins | Show which roles can invoke write/permission tools |
| `/permissions-allowlist add @role` | Owner / Admins | Grant a role access to write/permission tools |
| `/permissions-allowlist remove @role` | Owner / Admins | Revoke a role's access to write/permission tools |

---

## Upcoming features

### Phase 3 — Guarded writes ✅

- [x] `assign_role` / `remove_role` — add or remove a role from a member
- [x] `set_channel_permission` — set a permission overwrite for a role/user on a channel
- [x] `create_role` / `delete_role` — create or remove roles
- [x] `fix_bot_access` — diagnose why another bot can't operate in a channel and propose a minimal fix
- [x] Confirmation flow — bot proposes exact diff in the status embed, user reacts ✅/❌ to confirm or cancel
- [ ] Full audit logging for all executed write actions

### Phase 4 — Cleanup automation

- [ ] `clean_permissions` — sync channel overwrites to parent category, or strip redundant overwrites
- [ ] Scheduled permission health report
- [ ] Retention sweep — purge soft-deleted messages older than 2 months

### Phase 5 — Polish

- [ ] Per-user rate limiting and cooldowns
- [ ] Graceful pagination for large history fetches
- [ ] Friendly error messages for `discord.Forbidden` / `discord.HTTPException`
- [ ] Context window management — summarize older turns into a rolling memory string
- [ ] Slash shortcuts (`/summarize`, `/findmedia`) that bypass the LLM for speed

---

## Response UI

Every agent invocation produces two Discord messages:

**Status box** — posted immediately, edited in place as the agent works:
```
🧠 Thinking...
```
→ edited to:
```
🔧 `search_messages`...
✅ `search_messages` done
```

For write actions (Phase 3), the status box shows the proposed diff and waits for a reaction:
```
⚠️ Proposed change:
Grant @Moderators → View Channel, Send Messages in #staff-chat
React ✅ to confirm, ❌ to cancel
```

**Final answer box** — a separate embed posted once the loop completes. Clean answer, no step-by-step noise. This is also appended to the user's conversation history.

---

## Project structure

```
warden/
├── .env.example
├── pyproject.toml
├── bot/
│   ├── main.py               # entrypoint, gateway listener, slash commands
│   ├── agent/
│   │   ├── orchestrator.py   # Gemini tool-call loop
│   │   ├── tool_schemas.py   # function definitions + dispatcher
│   │   └── system_prompt.py  # base instructions and safety rules
│   ├── tools/
│   │   ├── search.py         # search_messages, find_message_by_context
│   │   ├── embeddings.py     # Gemini embedding helpers, cosine similarity
│   │   ├── media.py          # find_media
│   │   ├── summarize.py      # summarize_channel
│   │   ├── permissions.py    # list_permissions, list_roles, get_member_roles, scan_bots
│   │   ├── moderation.py     # manage_server (kick, ban, timeout, channels, move)
│   │   ├── reminders.py      # set_reminder, list_reminders, delete_reminder
│   │   └── audit.py          # get_audit_log, bulk_permission_audit
│   ├── indexer/
│   │   ├── listener.py       # real-time message index + embedding generation
│   │   ├── backfill.py       # one-time throttled history backfill on startup
│   │   └── retention_sweep.py # scheduled purge of old soft-deleted rows
│   ├── reminders/
│   │   └── scheduler.py      # 1-minute background task: fire due reminders
│   ├── guardrails/
│   │   ├── confirmation.py   # diff preview + ✅/❌ reaction confirm flow
│   │   └── auth.py           # allowlist check for write tools
│   ├── storage/
│   │   ├── db.py             # SQLite setup, settings helpers
│   │   └── models.py         # dataclasses for all table rows
│   └── utils/
│       ├── gemini.py         # shared Gemini client
│       ├── pagination.py     # chunked Discord history fetch helpers
│       └── formatting.py     # status embed, final-answer embed, diff rendering
└── tests/
    ├── conftest.py               # shared fixtures (tmp_db, env setup)
    ├── test_tools_permissions.py # permission + scan_bots tool unit tests
    ├── test_tools_search.py      # FTS search + helper unit tests
    ├── test_tools_reminders.py   # reminder CRUD + scheduler logic unit tests
    ├── test_orchestrator.py      # _strip_mention, _build_context unit tests
    ├── test_tool_schemas.py      # describe_write_action unit tests
    ├── test_guardrails.py        # auth allowlist unit tests
    ├── test_tools_moderation.py  # moderation tool unit tests + allowlist enforcement
    ├── test_tools_get_bot_commands.py # get_bot_commands unit tests
    └── test_llm_integration.py  # end-to-end: real Gemini API, verifies tool selection
```

---

## Testing

### Unit tests (no API calls)

```bash
uv run pytest -m "not llm" -v
```

134 tests covering tool logic, search backends, reminder CRUD, moderation actions, allowlist enforcement, orchestrator helpers, write-action descriptions, bot command inspection, and auth — all using an isolated in-memory SQLite DB via the `tmp_db` fixture. Discord objects are mocked; no real bot token or API key required.

### LLM integration tests (real Gemini API)

```bash
uv run pytest -m llm -v
```

45 tests that send natural-language prompts to the real Gemini API and assert that the correct tool was selected with the correct arguments extracted (channel IDs resolved from names, dates parsed, repeat intervals set, etc.). Requires `GEMINI_API_KEY` in `.env`. Tests are skipped automatically if the key is absent or set to the placeholder value.

A 4-second pause is added between each test to stay within the free-tier rate limit of 15 requests/minute. Full suite takes ~3.5 minutes.

### Run everything

```bash
uv run pytest -v
```

---

## Privacy notes

- Message content is persisted at rest in the SQLite database. Server members should be informed of this.
- A user's questions from one channel are visible to the bot's reasoning when they follow up in another channel. Worth disclosing (e.g. via a pinned message or `/about` command).
- Soft-deleted messages are retained for up to 2 months for audit purposes before being permanently purged.
