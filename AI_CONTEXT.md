# AI_CONTEXT.md – TRACE

> This file is the single re-entry point for AI assistants working on TRACE.
> Keep it current. It replaces reading 5 separate docs on every session start.

---

## Project

**Name:** TRACE – Token-aware Realtime AI Context Engine
**Type:** MCP Server (Python / FastMCP)
**License:** MIT
**Repo:** github.com/MyPatric69/trace
**Status:** v0.1.1 complete – v0.2.0 planning in progress

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
    ↕ MCP protocol
MCP Server Core  [server/main.py – FastMCP]
    ↕ internal calls
Local Intelligence Engine  [engine/]
    ↕ read/write
Data Layer  [AI_CONTEXT.md · ~/.trace/trace.db · ~/.trace/trace_config.yaml]
```

**Central storage:** All tools use `TraceStore.default()` which always points to
`~/.trace/trace.db` and `~/.trace/trace_config.yaml`. On first run the config is
bootstrapped by copying the project `trace_config.yaml` to `~/.trace/`.

---

## Project structure

```
trace/
├── AI_CONTEXT.md          ← this file
├── VISION.md
├── README.md
├── trace_config.yaml      ← source config (bootstrapped to ~/.trace/ on first run)
│
├── server/
│   ├── main.py            ← FastMCP entry point
│   ├── tools/
│   │   ├── status.py      ← get_status(), list_projects()
│   │   ├── context.py     ← update_context(), check_drift()
│   │   ├── costs.py       ← log_session(), get_costs(), get_tips()
│   │   └── session.py     ← new_session(), context compressor
│   └── config.py
│
├── engine/
│   ├── git_watcher.py
│   ├── doc_synthesizer.py
│   ├── token_tracker.py
│   ├── cost_controller.py
│   ├── store.py           ← SQLite interface – TraceStore.default() → ~/.trace/
│   ├── migrate.py         ← one-time migration: local trace.db → ~/.trace/trace.db
│   ├── auto_register.py   ← register_if_unknown() – called by post-commit hook
│   ├── session_logger.py  ← SessionEnd hook handler – parses transcript, logs tokens
│   └── providers/         ← pluggable provider adapters (v0.2.0)
│       ├── __init__.py    ← get_provider() – reads api_integration.provider from config
│       ├── base.py        ← AbstractProvider interface
│       ├── manual.py      ← default: reads from TraceStore (no credentials needed)
│       ├── anthropic.py   ← Anthropic Usage API (ANTHROPIC_ADMIN_API_KEY, Team/Enterprise only)
│       ├── openai.py      ← OpenAI Usage API (OPENAI_API_KEY)
│       └── vertexai.py    ← Google Vertex AI / Cloud Billing API
│
├── hooks/
│   ├── post-commit              ← Git Hook template
│   ├── install_hook.sh          ← install post-commit into a target repo
│   ├── setup_global_template.sh ← one-time: every new clone/init gets the hook
│   └── setup_claude_hook.sh     ← one-time: install SessionEnd hook in ~/.claude/settings.json
│
├── dashboard/
│   ├── server.py          ← FastAPI app (Phase 4 – optional web UI)
│   ├── index.html         ← single-page dashboard, auto-refresh every 30s
│   └── start.sh           ← bash dashboard/start.sh → http://localhost:8080
│
└── tests/

~/.trace/
├── trace.db               ← single central DB for all projects
└── trace_config.yaml      ← central config (bootstrapped from project on first run)
```

---

## Current phase: Phase 4 complete

**All 6 MCP tools + web dashboard + auto session logging – 194/194 tests green ✓**

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
- `dashboard/index.html` – single-page UI, auto-refresh every 30s, IBM Plex fonts, flat design
- `dashboard/start.sh` – `bash dashboard/start.sh` → http://localhost:8080
- `engine/store.py` – `get_token_summary()` + `get_sessions_with_projects()` added
- 9 REST endpoints: `/api/status`, `/api/projects`, `/api/costs[/{project}]`, `/api/tokens`, `/api/models`, `/api/drift/{project}`, `/api/sync/{project}`, `/api/tips`, `/api/new_session/{project}`

**Out of scope:**
- Multi-MCP proxy

---

## Tech stack

| Layer | Technology |
|---|---|
| MCP Server | Python 3.11+ / FastMCP |
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
- **`add_session()` returns `session_id` only** – cost is retrieved separately via `store.calculate_cost(model, input_tokens, output_tokens) → float`, which reads prices from `trace_config.yaml` and returns `0.0` for unknown models

---

## Next steps

**Phase 1 (complete):**
- [x] Create `trace_config.yaml` with model price table
- [x] Implement `engine/store.py` (SQLite schema)
- [x] Implement `server/main.py` (FastMCP bootstrap)
- [x] Implement `server/tools/costs.py` (`log_session`, `get_costs`)
- [x] End-to-end test: project registered, session logged, costs queried
- [x] Write tests (`tests/test_store.py`, `tests/test_costs.py`) – 24 passing
- [x] Final validation: 24/24 tests green, server starts clean

**Phase 2 (complete):**
- [x] Implement `engine/git_watcher.py` – post-commit hook
- [x] Implement `engine/doc_synthesizer.py` – `AI_CONTEXT.md` auto-update
- [x] Implement `update_context()` MCP tool
- [x] Implement `check_drift()` MCP tool
- [x] Install git hook in `hooks/post-commit` template

**Phase 3 (complete):**
- [x] Implement `engine/context_compressor.py` – session summary generation
- [x] Implement `new_session()` MCP tool – guided session reset with compressed handoff
- [x] Implement `get_tips()` MCP tool – active cost optimization recommendations

**Central DB migration (complete):**
- [x] `TraceStore.default()` – always uses `~/.trace/trace.db`
- [x] `TRACE_HOME` constant exported from `engine/store.py`
- [x] `engine/migrate.py` – one-time migration, idempotent CLI
- [x] All tools updated to `TraceStore.default()` (no more hardcoded config paths)
- [x] 141/141 tests green

**Git Template + Auto-register (complete – 11 tests):**
- [x] `engine/auto_register.py` – detects project name, registers in `~/.trace/trace.db`
- [x] `hooks/post-commit` – auto-register step before drift check
- [x] `hooks/setup_global_template.sh` – one-time setup: every new clone/init gets the hook
- [x] `hooks/install_hook.sh` – calls auto_register.py after hook install
- [x] 152/152 tests green

**Phase 4 (complete):**
- [x] `dashboard/server.py` – FastAPI app with 9 REST endpoints
- [x] `dashboard/index.html` – single-page UI (metrics, session health, drift, tips, model chart)
- [x] `dashboard/start.sh` – `bash dashboard/start.sh` → http://localhost:8080
- [x] `dashboard/favicon.svg` – SVG favicon, served at `/favicon.svg`
- [x] `tests/test_dashboard.py` – 26 tests green
- [x] `engine/store.py` – `get_token_summary()` + `get_sessions_with_projects()` added

**Auto session logging (complete – 16 tests):**
- [x] `engine/session_logger.py` – SessionEnd hook handler; calls `LiveTracker(cwd).clear()` on exit
- [x] `engine/transcript_parser.py` – shared `parse_transcript()` extracted from session_logger
  - `parse_transcript(path)` – reads JSONL; only processes `type:"assistant"` lines;
    deduplicates by `requestId`; sums `input_tokens + cache_creation_input_tokens`;
    detects most-common model
  - `detect_project(cwd)` – path match → name fallback against `~/.trace/trace.db`
- [x] `hooks/setup_claude_hook.sh` – installs SessionEnd + Stop in `~/.claude/settings.json` (migrates PostToolUse → Stop; Desktop App bug #42336)
- [x] `trace_config.yaml` + `~/.trace/trace_config.yaml` – added `claude-sonnet-4-6` model
- [x] `TROUBLESHOOTING.md` – Issue 9: sessions not auto-logging
- [x] 195/195 tests green

**Live Token Tracking (complete – 18 tests):**
- [x] `engine/transcript_parser.py` – shared parsing module (no duplication)
- [x] `engine/live_tracker.py` – `LiveTracker` class
  - `update(transcript_path, cwd)` – parses transcript, computes health (ok/warn/reset),
    writes `~/.trace/live_session.json`
  - `clear()` – deletes live file on SessionEnd
  - `get_live()` – returns data or None if absent / stale (>5 min)
- [x] `engine/live_session_hook.py` – Stop hook entry point
- [x] `dashboard/server.py` – `/api/live` endpoint
- [x] `dashboard/index.html` – Live Session panel (pulsing dot, 5s refresh)
- [x] `hooks/setup_claude_hook.sh` – idempotently adds Stop alongside SessionEnd; migrates PostToolUse → Stop
- [x] 213/213 tests green

**parse_transcript real-world format (Claude Code ≥ 1.x):**
- Each line has `type`: only `"assistant"` lines carry usage
- Usage is in `obj.message.usage`, not at top level
- Claude Code writes multiple lines per `requestId` → deduplicate by `requestId`
- Input total = `input_tokens + cache_creation_input_tokens` (`cache_read_input_tokens`
  excluded — it re-counts the same cached context on every API call, inflating session
  totals to millions of tokens for a session that never exceeded 200K at any point)
- Sanity warning logged if `input_tokens > 200_000` (not a cap; long sessions are valid)

**Provider adapters (complete – 30 tests):**
- [x] `engine/providers/base.py` – `AbstractProvider` interface (is_available, get_usage, get_models, get_name)
- [x] `engine/providers/manual.py` – default; reads TraceStore, always available, zero external deps
- [x] `engine/providers/anthropic.py` – Anthropic Usage API; credential from env or macOS Keychain; graceful fallback
- [x] `engine/providers/openai.py` – OpenAI Usage API + models list; graceful fallback
- [x] `engine/providers/vertexai.py` – Cloud Billing API; hardcoded Gemini pricing; budget_usd optional
- [x] `engine/providers/__init__.py` – `get_provider(config)` dispatches by `api_integration.provider`; falls back to ManualProvider when unavailable
- [x] `trace_config.yaml` – added `api_integration` section; version bumped to 0.2.0
- [x] `dashboard/server.py` – `GET /api/provider` endpoint
- [x] `tests/test_providers.py` – 30 tests green

**Provider rules:**
- All network calls have 5 s timeout; never crash TRACE
- Credentials never logged or returned in responses
- `get_provider()` guarantees `is_available() == True` on returned instance
- ManualProvider is the universal fallback (no external deps)

**WebSocket Push (complete – 12 tests):**
- [x] `dashboard/server.py` – `ConnectionManager` (connect/disconnect/broadcast); three background tasks: `_watch_live_file` (1s poll → `live_updated`), `_watch_db` (1s poll → `session_logged`), `_ping_clients` (30s keepalive); `lifespan` context for clean task lifecycle; `/ws` WebSocket endpoint
- [x] `dashboard/index.html` – `setupWebSocket()` replaces 5s live-poll; WS status dot in header (gray → teal on connect); `_startFallback()` (10s live poll) on disconnect/error; auto-reconnect after 3s; 30s `loadAll` backup unchanged
- [x] `tests/test_websocket.py` – 12 tests: ConnectionManager unit tests + `/ws` endpoint integration tests

**WebSocket behaviour:**
- `live_updated` → triggers `loadLive()` immediately
- `session_logged` → triggers `loadAll()` immediately  
- `ping` → keepalive, no UI action
- Multiple concurrent browser tabs each get their own connection; all receive broadcasts
- Fallback: if WS unavailable, falls back to 10s live-poll + 30s full-refresh automatically

**v0.2.0 complete** – 292/292 tests green ✓
- Config Auto-Sync ✅  Live Token Tracking ✅  Provider adapters ✅  WebSocket Push ✅

**Documentation (v0.2.0):**
- `README.md` – Provider configuration section (table, per-provider setup, adding a new provider); Token count accuracy disclaimer
- `TROUBLESHOOTING.md` – Issues 13 (token count accuracy), 14 (provider fallback / Admin key requirement)
- `dashboard/index.html` – Provider badge in header (shows provider name; amber "manual (fallback)" if configured provider unavailable); removed redundant clock/timestamp
- `AnthropicProvider` requires `ANTHROPIC_ADMIN_API_KEY` (Team/Enterprise only); standard `ANTHROPIC_API_KEY` rejected with clear log message

**Combined daily cost view (complete – 10 tests):**
- [x] `dashboard/server.py` – `GET /api/today` endpoint; merges today's DB token/cost summary with live session (project-filtered); returns DB fields + live fields + combined `total_*` fields; live section zeroed when no active session
- [x] `dashboard/index.html` – `loadMetrics()` uses `/api/today` as primary source; metric cards show combined DB + live totals; cost sub-label shows "X sessions + live" when live session active
- [x] `tests/test_dashboard.py` – 10 new tests: structure, all-zeros, DB-only, live-only, combined, cache summing, project filtering (include / exclude), exception resilience

**v0.3.0 Feature 1 – Token Calculator (complete – 16 tests):**
- [x] `dashboard/server.py` – `POST /api/tokenize` – counts tokens and estimates cost
  - Claude models: calls Anthropic `count_tokens` API (3s timeout) if `ANTHROPIC_API_KEY` set; graceful fallback to char approximation (`len / 3.5`) on failure or missing key; `method: "api"` | `"approximation"`
  - GPT models: word approximation (`words * 1.3`)
  - All other models: char approximation
  - Reads `input_per_1k` from `trace_config.yaml`; unknown model → `cost: 0.0`; empty/whitespace → `0 tokens`, no API call
- [x] `dashboard/server.py` – `GET /api/tokenize/models` – returns configured model list for the UI selector
- [x] `dashboard/index.html` – Token Calculator panel (panel 6, after Model Usage)
  - Model selector populated from `/api/tokenize/models` on init
  - Textarea (6 rows, resizable); 500ms debounce on input
  - Results row: `Tokens: N · [exact (API)|~estimate]` badge + `Cost: ~$X.XXXX`
  - Context bar: teal → amber (≥70%) → red (≥90%); Claude = 200k window, others = 128k
  - Model change triggers immediate re-tokenize
- [x] `tests/test_tokenize.py` – 16 tests: structure, empty/whitespace (no API call), approximation formulas (GPT word-count, unknown char-count), API path via mocked urlopen, API failure fallback, cost calculation, models list endpoint
- `ANTHROPIC_API_KEY` (standard key, not admin) – used only for `count_tokens`; completely optional

**v0.3.0 Feature 2 – Per-Turn DB Logging (complete – 15 tests):**
- [x] `engine/store.py` – `upsert_live_session(session_id, project_name, model, …)` – INSERT on first turn, UPDATE in place on subsequent turns; returns row id; notes format `"Live – Turn N"`
- [x] `engine/store.py` – `delete_live_session(session_id)` – removes the live record (guards with `notes LIKE 'Live – %'`); idempotent
- [x] `engine/store.py` – `session_id TEXT` column + `CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_session_id … WHERE session_id IS NOT NULL`; `_migrate_schema()` adds both idempotently
- [x] `engine/live_session_hook.py` – after `LiveTracker.update()`, calls `upsert_live_session()` when project is registered and session is not initializing; all errors silent
- [x] `engine/session_logger.py` – on SessionEnd, `delete_live_session(session_id)` before `add_session()` → live record replaced by final record; no duplicates on clean exit
- [x] `engine/migrate.py` – `add_session_id_column(db_path=None)` for pre-v0.3.0 DBs; called from `__main__`
- [x] `tests/test_per_turn_logging.py` – 15 tests: insert/update semantics, idempotency, schema migration, delete isolation (preserves final records), clean-exit no-duplicate scenario, two-session no-crosstalk

**Per-Turn Logging behaviour:**
- Live records: `session_id IS NOT NULL`, notes `"Live – Turn N"`
- Final records: `session_id IS NULL` (existing `add_session()` unchanged)
- Hard shutdown: last live record survives in DB
- Clean exit: live record deleted, final accurate record inserted via SessionEnd

**v0.3.0 Feature 3 – Hook Refinement (complete – 28 tests):**
- [x] `engine/hook_runner.py` – `SKIP_PREFIXES` list: `chore:`, `chore(`, `docs:`, `docs(`, `style:`, `style(`, `test:`, `test(`
- [x] `engine/hook_runner.py` – `should_skip(commit_message)` – case-insensitive prefix check; returns False for empty/unknown (when in doubt, synthesise)
- [x] `engine/hook_runner.py` – `run()` reads latest commit message early; if `should_skip()` is True, advances `.trace_sync` to current hash (drift stays accurate) and returns without synthesis; unknown/empty messages always synthesise
- [x] `engine/hook_runner.py` – logging to `~/.trace/session_logger.log` (skipped commits logged at INFO)
- [x] `tests/test_hook_refinement.py` – 28 tests: `should_skip()` True/False parametrised cases, case-insensitivity, integration: chore/docs/test skip → `.trace_sync` advances + `AI_CONTEXT.md` untouched; feat/fix → synthesis runs

**Hook Refinement behaviour:**
- Skip check happens before drift check – more efficient (no git diff for noise commits)
- `.trace_sync` always advances on skip so `check_drift()` stays accurate
- Affected prefixes: `chore`, `docs`, `style`, `test` (conventional commit types that don't change logic)
- Unrecognised prefixes (`feat`, `fix`, `refactor`, `perf`, `ci`, `build`, etc.) always synthesise

**v0.3.0 Feature 4 – MCP Server Panel (complete – 23 tests):**
- [x] `trace_config.yaml` + `~/.trace/trace_config.yaml` – `mcp_servers: []` section (manual config, populated via dashboard UI)
- [x] `dashboard/server.py` – three endpoints + config helpers:
  - `_load_central_config()` – reads `TRACE_HOME / "trace_config.yaml"`; returns `(path, dict)`
  - `_save_and_sync_config(path, config)` – writes central YAML; syncs to project `trace_config.yaml` when present
  - `_build_mcp_response(config)` – shared response builder; fixed 300-token baseline per server (`_TOKENS_PER_SERVER`); `source: "estimated"` always; `monthly_cost_estimate` via `avg_sessions_per_day × avg_turns × 30 × (total_tokens / 1k) × input_price`; `disclaimer` always present
  - `GET /api/mcp` – returns server list from config; never crashes if key absent
  - `POST /api/mcp` – adds server; validates name with `_NAME_RE = r"^[a-z0-9][a-z0-9\-]*$"` (422 on fail); 409 on duplicate; `status_code=201`
  - `DELETE /api/mcp/{name}` – removes server; 404 when not found
- [x] `dashboard/index.html` – MCP Servers panel with inline add/remove UI
  - Summary line: `Connected: N servers · ~M tokens/call`
  - `[✕]` remove button per server row; calls `DELETE /api/mcp/{name}`
  - Add form: text input + Add button; frontend lowercases before POST; inline error display
  - Monthly overhead estimate line (shown when > 0); disclaimer in amber always visible
  - `initMcpPanel()` wires Enter key on input; called from `init()`
- [x] `tests/test_mcp_panel.py` – 23 tests: GET structure/empty/disclaimer/total/missing-key; POST add/fields/total/duplicate-409/empty-422/whitespace-422/uppercase-422/spaces-422/hyphenated-201/persists; DELETE removes/updated-list/404/persists/total-decreases; disclaimer on all three verbs

**MCP Panel behaviour:**
- All numbers prefixed with `~` in the UI to signal estimates
- Backend validates name as-sent (no silent lowercasing); frontend lowercases before submit
- Disclaimer text: "Token overhead per MCP server is estimated from a fixed baseline of ~300 tokens per server per API call…"
- Panel is non-critical: read errors swallowed silently

**Bug fix – Session Health Bar misleading totals (UI only, no new tests → 369 total):**
- **Root cause:** "All Projects" view combined token totals across all sessions, compared against per-session thresholds (e.g. 4,809,880 / 100,000).
- [x] `dashboard/index.html` – health bar hidden for "All Projects" view; replaced with summary line "X sessions today across Y active projects" computed via parallel `/api/costs/{p}?period=today` calls

**Bug fix – detect_project subdirectory matching (2 new tests → 371 total):**
- **Root cause:** Claude Code passes the currently-open subdirectory as `cwd` in the Stop hook payload (e.g. `/project/app/ui`), not the project root. The exact-path match in `LiveTracker.__init__` failed.
- [x] `engine/live_tracker.py` – `LiveTracker.__init__` now tries three strategies in order:
  1. Exact resolved-path match (existing)
  2. Ancestor check: `resolved_cwd.relative_to(proj_resolved)` — succeeds when cwd is anywhere inside the registered project tree
  3. Name fallback: `resolved_cwd.name == proj_resolved.name`
- [x] `dashboard/index.html` – live panel now shows `"unknown project"` (amber) instead of empty string when `project == "unknown"`; session metrics still displayed
- [x] `tests/test_live_tracker.py` – two new tests: subdirectory match, name-only fallback match

**v0.3.0 Feature 4 refactor – MCP Panel config-backed (10 new tests → 379 total):**
- Replaced file-based discovery (`~/.claude/settings.json`, `claude_desktop_config.json`) with explicit manual config in `trace_config.yaml`
- Added `POST /api/mcp` and `DELETE /api/mcp/{name}` endpoints with full validation and persistence
- Added inline add/remove UI in dashboard; tests rewritten from 13 → 23 tests

**Next:**
- [ ] Provider Log Spam fix

---

## Last updated

2026-04-12 – Auto-synced 1 commit(s) to 2f0d5b0
