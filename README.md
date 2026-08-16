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
Agent Orchestrator ──► Gemini API (function calling loop)
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
| Secrets | `.env` via `python-dotenv` |

---

## Setup

### 1. Prerequisites

- Python 3.11+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- A Gemini API key ([Google AI Studio](https://aistudio.google.com))

### 2. Enable bot intents

In the Discord Developer Portal, enable:
- `MESSAGE_CONTENT`
- `GUILD_MEMBERS`
- `GUILD_MESSAGES`
- `GUILD_MESSAGE_REACTIONS`

### 3. Install

```bash
pip install -e .
```

### 4. Configure

```bash
cp .env.example .env
```

Fill in `.env`:

```env
DISCORD_TOKEN=your_discord_bot_token
GEMINI_API_KEY=your_gemini_api_key
GUILD_ID=your_discord_server_id
```

### 5. Run

```bash
python -m bot.main
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
- **`on_message_delete`** — soft-deletes (marks `deleted_at`); rows are excluded from search but retained for audit purposes until the retention sweep runs
- **`on_raw_message_delete`** — handles deletes for messages not in discord.py's local cache
- **Backfill** — on startup, paginates full channel history for all text channels with throttling so it doesn't hit Discord rate limits
- **Embeddings** — every new or edited message generates a Gemini embedding in a background task (fire-and-forget, never blocks indexing)

### Search tools

#### `search_messages(channel_id, query, author_id?, limit?)`

Searches the message index. Two backends, switchable at runtime:

| Backend | How | Cost |
|---|---|---|
| FTS (default) | SQLite FTS5 phrase match | Free |
| Semantic | Gemini `text-embedding-004` cosine similarity | Per-query API call |

Switch with `/search-mode` (admin only). Switching is instant — embeddings are always generated regardless of current mode, so no re-indexing is needed.

#### `find_message_by_context(channel_id, description)`

Finds a specific message by natural-language description ("the message where someone asked about the deploy"). Always uses semantic search with FTS as a fallback when embeddings aren't available yet.

### Summarize tool

#### `summarize_channel(channel_id, since?, limit?)`

Fetches up to `limit` messages from the index (oldest-first, with optional date filter). Returns raw messages for Gemini to summarize in its final response — avoids a nested API call.

### Media tool

#### `find_media(channel_id, media_type?, query?, limit?)`

Finds messages containing attachments of a given type (`image`, `video`, `audio`, `file`). Filters by attachment `content_type`. If `query` is provided, gates on FTS first before checking attachments.

### Storage

SQLite database with the following tables:

| Table | Purpose |
|---|---|
| `messages` | Full message index (content, attachments, embeds, soft-delete) |
| `messages_fts` | FTS5 virtual table over `messages.content` |
| `message_embeddings` | Gemini embedding vectors per message |
| `conversation_context` | Per-user conversation history (cross-channel) |
| `audit_log` | Every tool call: who ran what, with what args, and what happened |
| `permission_allowlist` | Roles authorised to use write/permission tools |
| `settings` | Runtime key/value config (e.g. `search_method`) |

All tables include a `guild_id` column for clean isolation.

### Slash commands

| Command | Who | What |
|---|---|---|
| `/search-mode [fts\|semantic]` | Admins | Switch the search backend |

---

## Upcoming features

### In progress — Phase 1 completion

- [ ] Gemini function schemas (`tool_schemas.py`) for all Phase 1 read-only tools
- [ ] Agent system prompt (`system_prompt.py`)
- [ ] Agent orchestrator (`orchestrator.py`) — Gemini tool-call loop, capped at 5 iterations
- [ ] Wire orchestrator into `on_message` (currently a `TODO`)
- [ ] Status embed + final answer embed (`formatting.py`) — live step-by-step feedback in channel

### Phase 2 — Permission introspection (read-only)

- [ ] `list_permissions(channel_id)` — dump permission overwrites for a channel
- [ ] `list_roles()` / `get_member_roles(user_id)` — inspect role structure
- [ ] `get_audit_log(action_type?, limit?)` — recent moderation/permission changes
- [ ] `bulk_permission_audit()` — scan all channels, flag anomalies (e.g. `@everyone` with admin, orphaned overwrites)

### Phase 3 — Guarded writes

Requires the requesting user to hold a role on the owner-configured allowlist — Discord's own `Manage Roles` permission is not sufficient on its own.

- [ ] `assign_role` / `remove_role` — add or remove a role from a member
- [ ] `set_channel_permission` — set a permission overwrite for a role/user
- [ ] `create_role` / `delete_role` — create or remove roles
- [ ] `fix_bot_access` — diagnose why another bot can't operate in a channel and propose a minimal fix
- [ ] Confirmation flow — bot proposes exact diff in a status embed, user reacts ✅/❌ to confirm or cancel
- [ ] `/permissions-allowlist add|remove|list` — owner-only command to configure who can invoke write tools
- [ ] Full audit logging for all executed write actions

### Phase 4 — Cleanup automation

- [ ] `clean_permissions` — sync channel overwrites to parent category, or strip redundant overwrites
- [ ] Scheduled permission health report
- [ ] Retention sweep — purge soft-deleted messages older than 2 months (scheduled, runs every 2 months)

### Phase 5 — Polish

- [ ] Per-user rate limiting and cooldowns
- [ ] Graceful pagination for large history fetches (Discord rate limits)
- [ ] Friendly error messages for `discord.Forbidden` / `discord.HTTPException`
- [ ] Context window management — cap conversation history at 20 turns; summarize older turns into a rolling memory string
- [ ] Optional slash shortcuts (`/summarize`, `/findmedia`) that bypass the LLM for speed

---

## Response UI

Every agent invocation produces two distinct Discord messages:

**Status box** — posted immediately, then edited in place as the agent works:
```
🔍 Searching #general for "deploy"...
```
→ edited to:
```
✅ Found 14 messages
🧠 Summarizing...
```

For write actions, the status box shows the proposed diff and waits for a reaction:
```
⚠️ Proposed change:
Grant @Moderators → View Channel, Send Messages in #staff-chat
React ✅ to confirm, ❌ to cancel
```

**Final answer box** — a separate embed posted once the loop completes. Clean, no step-by-step noise. This is also the message appended to the user's conversation history.

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
│   │   ├── tool_schemas.py   # function definitions for Gemini
│   │   └── system_prompt.py  # base instructions and safety rules
│   ├── tools/
│   │   ├── search.py         # search_messages, find_message_by_context
│   │   ├── embeddings.py     # Gemini embedding helpers, cosine similarity
│   │   ├── media.py          # find_media
│   │   ├── summarize.py      # summarize_channel
│   │   ├── permissions.py    # list/set/clean permissions, roles
│   │   └── audit.py          # get_audit_log, bulk_permission_audit
│   ├── indexer/
│   │   ├── listener.py       # real-time message index + embedding generation
│   │   ├── backfill.py       # one-time throttled history backfill on startup
│   │   └── retention_sweep.py # scheduled purge of old soft-deleted rows
│   ├── guardrails/
│   │   ├── confirmation.py   # diff preview + reaction confirm flow
│   │   └── auth.py           # allowlist check for write tools
│   ├── storage/
│   │   ├── db.py             # SQLite setup, settings helpers
│   │   └── models.py         # dataclasses for all table rows
│   └── utils/
│       ├── gemini.py         # shared Gemini client
│       ├── pagination.py     # chunked Discord history fetch helpers
│       └── formatting.py     # status embed, final-answer embed, diff rendering
└── tests/
    ├── test_tools_permissions.py
    ├── test_tools_search.py
    └── test_orchestrator.py
```

---

## Privacy notes

- Message content is persisted at rest in the SQLite database. Server members should be informed of this.
- A user's questions from one channel are visible to the bot's reasoning when they follow up in another channel. Worth disclosing (e.g. via a pinned message or `/about` command).
- Soft-deleted messages are retained for up to 2 months for audit purposes before being permanently purged.
- A user can request their data be purged — this is not yet automated but is on the roadmap.
