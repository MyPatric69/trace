# AI_CONTEXT.md – TRACE

> This file is the single re-entry point for AI assistants working on TRACE.
> Keep it current. It replaces reading 5 separate docs on every session start.

---

## Project

**Name:** TRACE – Token-aware Realtime AI Context Engine
**Type:** MCP Server (Python / FastMCP)
**License:** MIT
**Repo:** github.com/MyPatric69/trace
**Status:** Phase 1 – Active development

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
Data Layer  [AI_CONTEXT.md · trace.db · trace_config.yaml]
```

---

## Project structure

```
trace/
├── AI_CONTEXT.md          ← this file
├── VISION.md
├── README.md
├── trace_config.yaml      ← project registry + budgets + model prices
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
│   └── store.py           ← SQLite interface
│
├── hooks/
│   └── post-commit        ← Git Hook template
│
└── tests/
```

---

## Current phase: Phase 1 – In progress

**Goal:** Token/cost tracking that works immediately, no automation yet.

**Done:**
- `trace_config.yaml` – project registry, model prices, budget thresholds ✓
- `engine/store.py` – SQLite schema: projects + sessions tables ✓
- `server/main.py` – FastMCP server with real tool implementations ✓
- `server/tools/costs.py` – `log_session()` + `get_costs()` fully implemented ✓
- Folder structure: `server/`, `server/tools/`, `engine/`, `hooks/`, `tests/` ✓
- End-to-end test passed: project registered, session logged, costs queried ✓
- Tests: 24 passing (`tests/test_store.py` + `tests/test_costs.py`) ✓

**Next steps:**
- First commit: Phase 1 complete

**Out of scope (Phase 2+):**
- Git watching / automation
- AI_CONTEXT.md auto-generation
- Context compression

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

---

## Next steps

- [x] Create `trace_config.yaml` with model price table
- [x] Implement `engine/store.py` (SQLite schema)
- [x] Implement `server/main.py` (FastMCP bootstrap)
- [x] Implement `server/tools/costs.py` (`log_session`, `get_costs`)
- [x] End-to-end test: project registered, session logged, costs queried
- [x] Write tests (`tests/test_store.py`, `tests/test_costs.py`) – 24 passing
- [ ] First commit: Phase 1 complete

---

## Last updated
2026-04-10 – Phase 1 complete: all tools implemented, 24 tests passing
