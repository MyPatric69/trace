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
│   └── session_logger.py  ← SessionEnd hook handler – parses transcript, logs tokens
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

**Next: v0.2.0**
- [x] Config Auto-Sync (`engine/store.py` refactor)
- [x] Live Token Tracking (`engine/live_tracker.py`)
- [ ] Provider adapters (`engine/providers/`)
- [ ] WebSocket Push (`dashboard/`)

---

## Last updated

2026-04-12 – Explicit iterations[] guard in transcript_parser + live_tracker
