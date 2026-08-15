# Warden — Agentic Discord Bot Project Plan

## 1. Overview

A Discord bot that acts as an **agentic assistant** inside a server. Instead of fixed slash commands, users talk to it in natural language (mention it, DM it, or use a `/ask` command), and it uses **Gemini function calling** to decide which underlying action(s) to run — searching messages, summarizing a channel, finding media, or managing roles/permissions.

**Core idea:** Gemini is the "brain" that picks tools. Python + discord.py is the "hands" that actually calls the Discord API.

---

## 2. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Best Discord bot ecosystem, async-native, easy Gemini SDK |
| Discord library | `discord.py` (2.x) | Mature, async, full REST + gateway support, good permission/audit-log APIs |
| LLM | Gemini API (`google-genai` SDK) | User's choice — supports function calling / tool use |
| Storage | SQLite (or Postgres later) | Store conversation context, action audit log, cached channel summaries |
| Hosting | Docker container on a VPS (or Railway/Fly.io) | Needs to run 24/7 for gateway connection |
| Secrets | `.env` via `python-dotenv` | `DISCORD_TOKEN`, `GEMINI_API_KEY` |

Recommendation rationale: `discord.py` has first-class support for `PermissionOverwrite`, audit logs, and message history pagination — all needed here. Node/discord.js is equally capable, but Python pairs more naturally with the Gemini SDK for the agent loop.

---

## 3. High-Level Architecture

```
 @mention in any channel │ reply to bot's message │ DM
              │
              ▼
      [ discord.py Gateway Listener ]
              │  (resolve invoking user → load their cross-channel conversation thread)
              ▼
      [ Agent Orchestrator ]
              │  sends: conversation history + new message + tool schemas + context
              ▼
        [ Gemini API — function calling ]
              │  returns: tool_call(s) with arguments
              ▼
      [ Tool Executor Layer ]  ──► [ Discord REST API calls ]
              │
              ▼
      [ Guardrail / Confirmation Layer ]  (for destructive/permission actions)
              │
              ▼
      [ Response formatter ] ──► reply in the channel the prompt was typed in
              │
              ▼
      [ Conversation store update ] (append turn, tagged with source channel_id)
              │
              ▼
      [ Audit Logger ] (SQLite table: who asked, what ran, what changed)
```

The **Agent Orchestrator** runs a standard tool-use loop:
1. Send user message + system prompt + tool definitions to Gemini.
2. If Gemini returns a function call, execute it, feed the result back.
3. Repeat until Gemini returns a final natural-language answer.
4. Loop is capped (e.g., 5 iterations) to avoid runaway calls.

---

## 4. Invocation & Conversation Memory

**How to talk to the bot:**
- **`@Warden <question>`** in any channel — primary trigger. Recommended over a slash command because this is a conversational agent, not a single-shot utility; slash commands don't support natural back-and-forth well.
- **Reply to one of the bot's own messages** — continues the conversation without needing to re-mention it. Detected via `message.reference` pointing at a message authored by the bot.
- **DM the bot directly** — no mention needed, routes into the same per-user thread as server mentions.

**Memory model — one thread per user, spanning all channels:**
- Conversation history is keyed by `user_id` (not `channel_id`). A user asking something in `#general` and following up in `#dev-chat` an hour later gets continuity — Gemini sees the prior turns regardless of which channel they happened in.
- Each stored turn still tags the `channel_id` it was typed in and the `channel_id` the response was posted in, so the bot can cite "you asked this in #general" and so the reply itself is posted back into whichever channel the new message came from — memory is shared, but replies still show up locally where the user is talking.
- **Context window management:** don't feed unlimited history to Gemini every call. Cap to the last N turns (e.g. 20) or a token budget; older turns can be periodically summarized into a rolling "memory summary" string and prepended, so long-running threads don't blow the context window or the API bill.
- **Guild-only scope:** since this is a single-server bot, the user's thread only ever contains that one server's context — no cross-server leakage question to worry about, consistent with the isolation decision in Section 12.
- **Privacy note to flag for server members:** a user's questions asked in one channel are now visible to the bot's reasoning even when they follow up in a completely different channel. Worth a one-line disclosure (e.g. in a pinned message or `/about` command) since this is a step beyond normal per-channel bot behavior.

---

## 5. Response UI — Status Box + Final Answer Box

Every agent invocation produces **two visually distinct pieces**, not one wall of text:

**1. Status box** — posted immediately as an embed, then *edited in place* (not re-posted) as the agent works through its tool-call loop. Each step updates the same message:
```
🔍 Searching #general for "deploy"...
```
→ edited to:
```
✅ Found 14 messages
🧠 Summarizing...
```
This gives the user live feedback instead of silence during multi-step tool loops, and it's also **where the write-action confirmation lives** — resolving Open Question #3:
```
⚠️ Proposed change:
Grant @Moderators → View Channel, Send Messages in #staff-chat
React ✅ to confirm, ❌ to cancel
```
The box then edits to `✅ Applied` or `❌ Cancelled` once resolved. Reaction-based confirmation (✅/❌) fits better than a `/confirm` slash command here, since the proposed diff is already visible right above the reaction — no need to re-type anything.

**2. Final answer box** — a separate embed message posted once the loop completes. Keeps the actual answer clean and separate from the step-by-step trail, so scrolling back through a channel later shows readable answers without the "thinking" noise cluttering them. This is the message that also gets appended to the user's cross-channel conversation history (Section 4).

**Implementation note:** editing a message in place (status box) is a single `message.edit()` call per step — cheap and avoids channel spam. The final box is a fresh `channel.send()` so it's distinguishable at a glance (different embed color/icon convention, e.g. grey for status, blue for final answer).

---

## 6. Background Message Indexer (non-LLM)

A separate, always-on component — **no Gemini call involved**. It listens to raw gateway events and keeps a local index up to date in real time, so the agent's read-only tools query the index instead of re-paginating Discord's live history on every request.

**How it works:**
- Hooks `on_message`, `on_message_edit`, `on_message_delete`, and `on_raw_message_delete` (raw needed for messages not in the local cache).
- On `on_message`: writes `message_id, channel_id, author_id, content, attachment urls/types, embed data, created_at` to the index immediately — synchronous with the event, not batched, so search is always current.
- On `on_message_edit`: updates the stored content (optionally keeps edit history if you want an audit trail of edits).
- On `on_message_delete`: **soft-deletes** — marks `deleted_at` rather than removing the row immediately, so moderation/audit lookups can still reference recently-deleted content. **Resolved retention policy:** a scheduled sweep job runs every 2 months and permanently purges any row where `deleted_at` is older than 2 months. Until swept, soft-deleted rows are excluded from normal `search_messages`/`find_media`/`summarize_channel` results by default (they'd only surface through an explicit moderation-focused tool, if one is added later) — they're retained for the audit trail, not for everyday search.
- **Backfill on join / first run**: since the gateway only streams *new* messages, the bot needs a one-time backfill job per channel using `channel.history(limit=None)` to populate history that existed before the bot started indexing. This is rate-limit-sensitive and should run as a background task with throttling, not block startup.

**Storage:** SQLite with FTS5 (full-text search virtual table) is enough for a single mid-size server; move to Postgres + `tsvector`/`pg_trgm` if the server is large. Every table (`messages`, `audit_log`, `conversation_context`) includes a `guild_id` column even though this deployment only ever serves one guild — this keeps the schema consistent if you ever spin up a second isolated instance, and makes the `GUILD_ID` boundary explicit rather than implicit. This resolves **Open Question #2** from Section 12 — search will be backed by a persistent index rather than live pagination.

**Why this matters for the existing tools:**
- `search_messages` and `find_message_by_context` now query the index (fast, no Discord API rate-limit risk) instead of calling `channel.history()` per request.
- `find_media` similarly queries indexed `attachments`/`embeds` rows instead of re-scanning.
- `summarize_channel` can pull a precise date/message-count range instantly from the index.

**Scope/permission note:** the indexer only stores what the bot's `MESSAGE_CONTENT` intent already lets it see — no new permission requirement, but it does mean message content is now persisted at rest, which is worth flagging to server members (data retention/privacy policy, and a way to purge on request).

---

## 7. Feature → Tool Mapping

Each feature becomes a discrete "tool" (function) exposed to Gemini. Keeping tools narrow and typed makes the agent reliable and auditable.

### Read-only / low-risk tools
| Tool | Description | Discord API used |
|---|---|---|
| `search_messages(channel_id, query, author=None, limit=50)` | Full-text-ish search across recent channel history for a keyword/phrase | `channel.history()` + local filtering (Discord has no native search API for bots — must paginate & filter, or use search via user-installed indexing) |
| `find_message_by_context(channel_id, description)` | Semantic search — feeds candidate messages to Gemini to pick the best match | `channel.history()` + Gemini re-ranking |
| `summarize_channel(channel_id, since=None, limit=200)` | Pulls N messages, sends to Gemini for a structured summary | `channel.history()` |
| `find_media(channel_id, media_type="image", query=None, limit=200)` | Scans messages for attachments/embeds matching type/keywords | `message.attachments`, `message.embeds` |
| `list_permissions(channel_id or role_id)` | Dumps current permission overwrites / role permissions | `channel.overwrites`, `guild.roles` |
| `list_roles()` / `get_member_roles(user_id)` | Inspect role structure | `guild.roles`, `member.roles` |
| `get_audit_log(action_type=None, limit=20)` | Review recent moderation/permission changes | `guild.audit_logs()` |

### Write / destructive tools (require confirmation guardrail)
| Tool | Description | Discord API used |
|---|---|---|
| `assign_role(user_id, role_id)` / `remove_role(user_id, role_id)` | Add/remove a role from a member | `member.add_roles()` / `remove_roles()` |
| `set_channel_permission(channel_id, target_id, allow=[], deny=[])` | Set a specific permission overwrite for a role/user on a channel | `channel.set_permissions()` |
| `clean_permissions(channel_id, policy="sync_to_category" \| "remove_redundant")` | Remove overwrites that duplicate the parent category, or reset to category defaults | `channel.permissions_synced`, `channel.edit(overwrites=...)` |
| `create_role(name, permissions, color)` | Create a new role | `guild.create_role()` |
| `delete_role(role_id)` | Remove a role | `role.delete()` |
| `bulk_permission_audit(guild_id)` | Scan all channels, flag anomalies (e.g., @everyone with admin, orphaned overwrites for deleted users/roles) | `guild.channels` + `channel.overwrites` |
| `fix_bot_access(channel_id, bot_name_or_id)` | Diagnose why a *different* bot can't operate in a channel — walks the effective permission stack (server role → category → channel overwrite), flags which required permissions (View Channel, Send Messages, Read Message History, Embed Links, Connect/Speak for voice, etc.) are denied and why, and proposes the minimal overwrite fix | `channel.permissions_for(member)`, `guild.roles`, `channel.overwrites`, `category.overwrites` |

**Guardrail rule:** any tool in the "write" table requires (a) the requester to hold a role on an **explicit allowlist configured by the server owner** — not just anyone who happens to have `Manage Roles`/`Manage Channels` via Discord's own permission system — and (b) a confirmation step, shown in the status box (Section 5): the bot proposes the exact diff ("Will grant @Moderators: View Channel, Send Messages in #staff-chat") and waits for a ✅ reaction before executing. The allowlist is separate from Discord's native permission system by design — a user could technically have `Manage Roles` at the Discord level but still be blocked from using the bot's permission tools unless the owner has explicitly added their role to the allowlist. This is stricter and intentional: it prevents scope creep where "can manage permissions manually" silently becomes "can direct the bot to manage permissions."

**Configuring the allowlist:** a simple **owner-only slash command** (e.g. `/permissions-allowlist add @role` / `remove @role` / `list`) — restricted to the server owner or `Administrator` at setup time, since that's the one bootstrapping check that has to fall back to Discord's native permission system before the allowlist itself exists. Writes to the `PermissionAllowlist` table (`role_id`, `added_by`, `added_at`). Every write-tier tool checks the requester's roles against this table first — before even generating the confirmation diff.

---

## 8. Discord Bot Setup Requirements

**Privileged Gateway Intents** (enable in Developer Portal):
- `MESSAGE_CONTENT` — required to read message text for search/summarize
- `GUILD_MEMBERS` — required to resolve users/roles for permission tools
- `GUILD_MESSAGES`, `GUILD_MESSAGE_REACTIONS` — standard

**Bot Permissions (invite scope):**
- View Channels, Read Message History, Send Messages, Embed Links
- Manage Roles, Manage Channels (only if permission-management features are enabled)
- View Audit Log

**Role hierarchy constraint to document for the user:** the bot's own role must sit *above* any role it needs to assign/remove, and Discord will silently reject role edits above its position — the tool executor should catch this (`discord.Forbidden`) and report it clearly rather than fail silently.

---

## 9. Project File Structure

```
warden/
├── CLAUDE.md                 # this file
├── .env.example
├── requirements.txt
├── bot/
│   ├── main.py               # entrypoint, gateway listener, event handlers
│   ├── agent/
│   │   ├── orchestrator.py   # Gemini tool-call loop
│   │   ├── tool_schemas.py   # JSON schemas for all tools (Gemini function defs)
│   │   └── system_prompt.py  # base instructions, tone, safety rules
│   ├── tools/
│   │   ├── search.py         # search_messages, find_message_by_context (query the index)
│   │   ├── media.py          # find_media (queries the index)
│   │   ├── summarize.py      # summarize_channel (pulls range from the index)
│   │   ├── permissions.py    # list/set/clean permissions, roles, fix_bot_access
│   │   └── audit.py          # get_audit_log, bulk_permission_audit
│   ├── indexer/
│   │   ├── listener.py       # on_message/on_message_edit/on_message_delete hooks (no LLM)
│   │   ├── backfill.py       # one-time throttled history backfill per channel on join/startup
│   │   └── retention_sweep.py # scheduled job: purge soft-deleted rows with deleted_at older than 2 months
│   ├── guardrails/
│   │   ├── confirmation.py   # diff preview + reaction/slash confirm flow
│   │   └── auth.py           # checks requester's roles against the owner-configured allowlist for write/permission tools
│   ├── storage/
│   │   ├── db.py             # SQLite (FTS5) setup
│   │   └── models.py         # MessageIndexEntry, AuditLogEntry, ConversationContext (keyed by user_id, spans channels), PermissionAllowlist (owner-configured role_ids)
│   └── utils/
│       ├── pagination.py     # chunked history fetch helpers
│       └── formatting.py     # status-box embed (editable), final-answer embed, diff rendering
└── tests/
    ├── test_tools_permissions.py
    ├── test_tools_search.py
    └── test_orchestrator.py
```

---

## 10. Agent System Prompt — Key Rules to Encode

- Only call one tool at a time unless the user clearly asked for a multi-step action; explain the plan before executing write actions.
- Never guess a channel/role/user ID — resolve names to IDs via a lookup tool first if ambiguous, and ask the user to disambiguate if multiple matches exist.
- For any `write` tool, always produce a plain-language diff and require explicit confirmation before calling it.
- Refuse permission-management write actions unless the requesting user holds a role on the owner-configured allowlist (Section 12, item 5) — a user's own Discord permissions are not sufficient on their own.
- Summaries should cite message authors/timestamps, not just paraphrase generically.
- Log every executed tool call (tool name, args, requester, result) to the audit table.

---

## 11. Development Phases

**Phase 1 — Indexer + read-only core**
- Background indexer live first: `on_message`/`on_message_edit`/`on_message_delete` hooks + one-time backfill per channel (no LLM involved)
- Bot connects, listens for mentions/`/ask`
- `search_messages`, `summarize_channel`, `find_media` — all querying the index, not live history
- Basic Gemini tool-call loop, no writes yet

**Phase 2 — Permission introspection**
- `list_permissions`, `list_roles`, `get_audit_log`, `bulk_permission_audit`
- Still read-only — lets users trust the bot's understanding before it can act

**Phase 3 — Guarded writes**
- `assign_role`, `set_channel_permission`, `create_role`/`delete_role`
- Confirmation flow + auth checks
- Full audit logging

**Phase 4 — Cleanup automation**
- `clean_permissions` policies (sync-to-category, remove-redundant, remove-orphaned)
- Scheduled/optional periodic permission-health report
- Indexer retention sweep: scheduled job (every 2 months) permanently purging soft-deleted rows past retention

**Phase 5 — Polish**
- Rate limiting / cooldowns per user
- Pagination for large history fetches (Discord history rate limits)
- Error messages mapped from `discord.Forbidden` / `discord.HTTPException`
- Optional: slash-command shortcuts for common actions (`/summarize`, `/findmedia`) that skip the LLM for speed

---

## 12. Open Questions / Decisions Needed Before Building

1. ~~Single-server bot, or multi-server?~~ **Resolved:** single-server bot. Each deployment serves exactly one guild — no cross-server config lookup, no multi-tenant routing. To keep isolation clean and the codebase future-proof (in case you ever want to run a second instance for a different server), all storage tables still key rows by `guild_id`, and the indexer/backfill only ever operates on channels within the configured `GUILD_ID` from `.env`. This simplifies the confirmation/auth flow too — no need to look up "which server is this admin acting in," since there's only one.
2. ~~Should `search_messages` be limited to recent history or backed by a persistent index?~~ **Resolved:** persistent index (Section 6) — remaining decision is just SQLite-FTS5 vs. Postgres, based on expected server size.
3. ~~Confirmation UX: reaction-based or `/confirm` slash command?~~ **Resolved:** reaction-based (✅/❌), shown directly in the status box alongside the proposed diff (Section 5) — no separate command needed.
4. ~~Should Gemini calls be per-message (cheap, stateless) or maintain rolling conversation memory per channel/user?~~ **Resolved:** rolling memory, keyed **per-user across all channels** (Section 4), not per-channel. Remaining sub-decision: exact turn cap / summarization strategy for context window management.
5. ~~Who can invoke permission-management tools?~~ **Resolved:** restricted to an explicit **role allowlist** configured by the server owner — not just "anyone with the matching Discord permission." See Section 10 (Auth) for the enforcement design.

---

*Next step: once these decisions are confirmed, scaffold Phase 1 (read-only core) as working code.*