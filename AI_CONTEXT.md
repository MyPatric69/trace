# AI_CONTEXT.md – TRACE

> This file is the single re-entry point for AI assistants working on TRACE.
> Keep it current. It replaces reading 5 separate docs on every session start.
> 
> **New sessions:** Also read `WORKING_WITH_CLAUDE.md` for collaboration guidelines.

---

## Project

**Name:** TRACE – Token-aware Realtime AI Context Engine
**Type:** MCP Server (Python / FastMCP)
**License:** MIT
**Repo:** github.com/MyPatric69/trace
**Status:** All 4 phases complete – 469/469 tests green ✓

---

## What TRACE does

TRACE is an MCP server that integrates into AI development environments (Claude Code, Cursor, Codex). It provides two core capabilities:

1. **Token cost tracking** – logs and aggregates API token consumption per project and session
2. **Context intelligence** – keeps `AI_CONTEXT.md` automatically current via git hook integration

Heavy computation runs locally (zero API cost). The MCP layer returns only compressed results.

---

## Architecture (current)

```
IDE Layer (Claude Code / Cursor / Codex)
    ↕ MCP protocol                       ↕ PostToolUse / Stop hook
MCP Server Core  [server/main.py]        Live Tracker  [engine/live_tracker.py]
    ↕ internal calls                         ↕ writes
Local Intelligence Engine  [engine/]    ~/.trace/live_session.json
    ↕ read/write
Data Layer  [~/.trace/trace.db · ~/.trace/trace_config.yaml]
    ↕ read
Dashboard  [dashboard/server.py – FastAPI + WebSocket → http://localhost:8080]
```

**Central storage:** All tools use `TraceStore.default()` → `~/.trace/trace.db` and
`~/.trace/trace_config.yaml`. On first run the config is bootstrapped from the project
`trace_config.yaml` to `~/.trace/`.

---

## Project structure

```
trace/
├── AI_CONTEXT.md          ← this file
├── CLAUDE.md
├── VISION.md
├── README.md
├── WORKING_WITH_CLAUDE.md
├── TROUBLESHOOTING.md
├── trace_config.yaml      ← source config (bootstrapped to ~/.trace/ on first run)
├── requirements.txt
│
├── server/
│   ├── main.py            ← FastMCP entry point (6 tools)
│   └── tools/
│       ├── costs.py       ← log_session(), get_costs()
│       ├── context.py     ← update_context(), check_drift()
│       └── session.py     ← new_session(), get_tips()
│
├── engine/
│   ├── store.py           ← SQLite interface – TraceStore.default() → ~/.trace/
│   ├── live_tracker.py    ← PostToolUse hook – incremental transcript parse → live_session.json
│   ├── live_session_hook.py ← Stop hook handler – fires after each completed response
│   ├── transcript_parser.py ← Shared transcript token-counting logic
│   ├── session_logger.py  ← SessionEnd hook – parses full transcript, logs to DB
│   ├── handoff_builder.py ← build_handoff() – enriches compress() output with CLAUDE.md/backlog/git context
│   ├── git_watcher.py
│   ├── doc_synthesizer.py
│   ├── context_compressor.py
│   ├── hook_runner.py
│   ├── auto_register.py   ← register_if_unknown() – called by post-commit hook
│   ├── migrate.py         ← one-time migration: local trace.db → ~/.trace/trace.db
│   └── providers/         ← pluggable provider adapters
│       ├── __init__.py    ← get_provider() – reads api_integration.provider from config
│       ├── base.py        ← AbstractProvider interface
│       ├── manual.py      ← default: reads from TraceStore (no credentials needed)
│       ├── anthropic.py   ← Anthropic Usage API (ANTHROPIC_ADMIN_API_KEY)
│       ├── openai.py      ← OpenAI Usage API (OPENAI_API_KEY)
│       └── vertexai.py    ← Google Vertex AI / Cloud Billing API
│
├── hooks/
│   ├── post-commit              ← Git Hook template
│   ├── install_hook.sh
│   ├── setup_global_template.sh
│   └── setup_claude_hook.sh    ← installs PostToolUse + Stop hooks in ~/.claude/settings.json
│
├── dashboard/
│   ├── server.py          ← FastAPI app + WebSocket + 15+ REST endpoints
│   ├── index.html         ← single-page UI, auto-refresh every 120s
│   ├── favicon.svg
│   └── start.sh           ← bash dashboard/start.sh → http://localhost:8080
│
├── docs/
│   ├── manifest_de.html
│   └── manifest_en.html
│
└── tests/                 ← 434 tests, all green

~/.trace/
├── trace.db               ← single central DB for all projects
├── trace_config.yaml      ← central config (bootstrapped from project on first run)
├── live_session.json      ← current in-progress session (written by live_tracker.py)
├── last_health.json       ← persisted health state across browser refreshes
└── session_logger.log     ← hook error log
```

---

## Current phase: All phases complete

**469/469 tests green ✓ (2026-04-16)**

**Phase 1 (complete – 24 tests):**
- `trace_config.yaml` – project registry, model prices, session thresholds, budgets
- `engine/store.py` – SQLite schema, `TraceStore` with `add_session()` → `int`, `calculate_cost()` → `float`
- `server/tools/costs.py` – `log_session()` + `get_costs()` with period filters

**Phase 2 (complete – 70 tests):**
- `engine/git_watcher.py` – `GitWatcher` class
- `engine/doc_synthesizer.py` – `DocSynthesizer`, delta-based `AI_CONTEXT.md` updates
- `server/tools/context.py` – `check_drift()` + `update_context()` MCP tools
- `engine/hook_runner.py` + `hooks/post-commit` + `hooks/install_hook.sh` – git hook system

**Phase 3 (complete – 47 tests):**
- `engine/context_compressor.py` – `ContextCompressor`, token-optimized re-entry prompt
- `server/tools/session.py` – `new_session()` + `get_tips()` MCP tools

**Phase 4 (complete – 26 tests):**
- `dashboard/server.py` – FastAPI app, reads `~/.trace/trace.db` via `TraceStore`
- `dashboard/index.html` – single-page UI, IBM Plex fonts, flat design
- `engine/store.py` – `get_token_summary()` + `get_sessions_with_projects()` added

**Dashboard feature expansions (complete):**
- **Live session tracking** – `engine/live_tracker.py` (PostToolUse hook), `engine/live_session_hook.py` (Stop hook), `engine/transcript_parser.py` (shared parsing); `/api/live` + `/api/live/clear` endpoints; WebSocket push to connected browsers
- **Turns tracking** – `turns` column in `sessions` table; `upsert_live_session()` + `delete_live_session()` in store; turns displayed in live panel, health bar, daily summary
- **Provider badges** – `resolve_provider(model)` helper + `/api/providers` endpoint; per-project badges with model subtitles; provider detection: `claude-*` → anthropic, `gpt-*/o1-*/o3-*/o4-*` → openai, `gemini-*/gemma-*` → google
- **7-day date picker** – `/api/stats/{date}` endpoint + `/api/today` summary
- **Configurable health thresholds** – green/yellow/red read from `trace_config.yaml` (no hardcoded 100k)
- **MCP server panel** – add/remove MCP servers via UI; reads from both Claude config locations
- **Persistence** – project filter in localStorage; health state in `~/.trace/last_health.json`
- **Auto-refresh** – 120s interval (was 30s); WebSocket used for live data push

**Dashboard REST endpoints (current):**
```
GET  /api/status
GET  /api/projects
GET  /api/costs             ?period=
GET  /api/costs/{project}   ?period=
GET  /api/tokens            ?project= &period=
GET  /api/stats/{date}      ?project=
GET  /api/today             ?project=
GET  /api/models            ?period= &project=
GET  /api/providers
GET  /api/provider          ?period=
GET  /api/drift/{project}
GET  /api/sync/{project}
GET  /api/live              ?project=
POST /api/live/clear
GET  /api/tips              ?project_name=
GET  /api/new_session/{project}  ?dry_run=
WS   /ws
```

**Enriched handoff prompt (complete – 30 tests):**
- `engine/handoff_builder.py` – `build_handoff(repo_path, base_prompt)` enriches the compress() output with: `## Current Phase` (from CLAUDE.md), `## Open Task` (first incomplete checkbox from highest-numbered backlog/epic-*.md), `## Files to Read First` (git diff HEAD~3, max 5, filtered to .ts/.tsx/.md/.py/.yaml), `## Known Constraints` (CLAUDE.md Runtime Rules), `## Test Command` (test/type-check line from CLAUDE.md Dev Commands)
- Staleness warning prepended when AI_CONTEXT.md mtime > 2 days
- `server/tools/session.py` – calls `build_handoff` after `compress()`, falls back silently on error
- `tests/test_handoff_builder.py` – 30 tests

**Out of scope:**
- Multi-MCP proxy

---

## Tech stack

| Layer | Technology |
|---|---|
| MCP Server | Python 3.11+ / FastMCP |
| Dashboard | FastAPI + WebSocket |
| Storage | SQLite (via `sqlite3` stdlib) |
| Config | YAML (`pyyaml`) |
| Git integration | `gitpython` (Phase 2) |
| Package mgmt | `pyenv` + `pip` |

---

## Key decisions

- **Local-heavy, API-light** – all heavy work in engine/, MCP returns summaries only
- **SQLite over flat files** – queryable, no extra dependencies, single file per workspace
- **FastMCP over raw MCP** – reduces boilerplate, Pythonic, well-maintained
- **Delta-based doc updates** – never full rewrites, only targeted patches (Phase 2)
- **`add_session()` returns `session_id` only** – cost retrieved separately via `store.calculate_cost()`
- **Prefix matching for model prices** – handles date-suffixed model strings (e.g. `claude-sonnet-4-5-20251022`)
- **Incremental transcript parsing** – `live_tracker.py` tracks byte offset, only parses new lines per call
- **`upsert_live_session()` not `add_session()`** – live sessions update in place; `delete_live_session()` called at SessionEnd before `add_session()` finalises

---

## Next steps

No open items – all phases and feature expansions complete. Tests green.

---

## Last updated

2026-04-16 – handoff_builder: multi-line test command extraction, join with &&, 200-char truncation (469/469 tests green)
