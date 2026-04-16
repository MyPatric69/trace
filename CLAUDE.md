# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> For full project context, always read `AI_CONTEXT.md` first – it is the authoritative re-entry point and replaces reading multiple separate docs.

## Project context

TRACE is an MCP server (Python / FastMCP) that provides token cost tracking and context intelligence for AI-assisted development.

## Working directory

/Users/patric/My AI Companion/github/trace

## Commands

```bash
# Run the MCP server
python server/main.py

# Smoke-test the store (initialises trace.db)
python engine/store.py

# Run tests
pytest tests/

# Run a single test file
pytest tests/test_store.py -v
```

No build step. No compiled assets. Pure Python.

## Architecture

```
server/main.py              FastMCP entry point – registers 6 MCP tools
server/tools/costs.py       log_session(), get_costs()
server/tools/context.py     check_drift(), update_context()
server/tools/session.py     new_session(), get_tips()
engine/store.py             SQLite interface – the only layer that touches trace.db
engine/live_tracker.py      PostToolUse hook – incremental transcript parse → live_session.json
engine/live_session_hook.py Stop hook handler – fires after each completed response
engine/transcript_parser.py Shared transcript parsing (token counting)
engine/session_logger.py    SessionEnd hook – parses full transcript, logs to DB
dashboard/server.py         FastAPI web UI + REST + WebSocket endpoints
trace_config.yaml           Single source of truth: db path, model prices, budgets, health thresholds
```

**Data flow:** MCP tool call → `server/tools/*.py` → `engine/store.py` → `trace.db`. Tools never query SQLite directly; they go through `TraceStore`.

**Cost calculation** lives entirely in `TraceStore._calculate_cost()` – it reads model prices from `trace_config.yaml` at init time. Adding a new model means adding it to the `models:` block in the config, nothing else.

**`trace_config.yaml` is loaded once** in `TraceStore.__init__()`. If the config changes at runtime, the store must be re-instantiated.

## Key conventions

- Heavy logic lives in `engine/` – MCP layer returns summaries only
- SQLite via `store.py` – no external DB dependencies
- Config via `trace_config.yaml` – no hardcoded values anywhere
- Python 3.11+ – stdlib first, minimal external dependencies
- After every session: update Next Steps in `AI_CONTEXT.md`

## Key constraints

- `engine/store.py` uses **stdlib only** (`sqlite3`, `pathlib`, `datetime`) plus `pyyaml`. No extra dependencies.
- `trace.db` is gitignored. Schema is created by `TraceStore.init_db()` – always call this before first use.
- `trace_config.local.yaml` (gitignored) can override `trace_config.yaml` for local dev – not yet wired in, but reserved by `.gitignore`.
- Phase 2+ features (git watching, doc synthesis, context compression) are **out of scope** until Phase 1 is complete and committed.

## Phase status

- Phase 1 ✅ Foundation – store.py, trace_config.yaml, FastMCP bootstrap
- Phase 2 ✅ Context Intelligence – git watcher, doc synthesizer, hook system
- Phase 3 ✅ Optimization – context compressor, session tools
- Phase 4 ✅ Dashboard – FastAPI + web UI, live session tracking, provider badges, turns tracking
  - 434/434 tests green (2026-04-16, commit 737055a)
