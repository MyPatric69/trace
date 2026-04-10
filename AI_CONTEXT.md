# AI_CONTEXT.md – TRACE

> This file is the single re-entry point for AI assistants working on TRACE.
> Keep it current. It replaces reading 5 separate docs on every session start.

---

## Project

**Name:** TRACE – Token-aware Realtime AI Context Engine
**Type:** MCP Server (Python / FastMCP)
**License:** MIT
**Repo:** github.com/MyPatric69/trace
**Status:** Phase 2 complete – Phase 3 ready to start

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

## Current phase: Phase 2 – Context Intelligence

**Goal:** Automate `AI_CONTEXT.md` updates via git hook integration.

**Phase 1 delivered (complete and verified – all bugs fixed, 24/24 tests green ✓):**
- `trace_config.yaml` – project registry, model prices, budget thresholds
- `engine/store.py` – SQLite schema, `TraceStore` with `add_session()` → `int`, `calculate_cost()` → `float`
- `server/main.py` – FastMCP server, runnable via `python server/main.py`
- `server/tools/costs.py` – `log_session()` + `get_costs()` with period filters
- `tests/` – 24 passing tests (unit + integration)

**Phase 2 next steps:**
- [x] Implement `engine/git_watcher.py` – `GitWatcher` class, 30 tests passing ✓
- [x] Implement `engine/doc_synthesizer.py` – `DocSynthesizer` class, 23 tests passing ✓
- [x] Implement `update_context()` MCP tool – `server/tools/context.py` ✓
- [x] Implement `check_drift()` MCP tool – `server/tools/context.py` ✓
- [ ] Install git hook template in `hooks/post-commit`

**Phase 3 (next):**
- [ ] Implement `engine/context_compressor.py` – session summary generation
- [ ] Implement `new_session()` MCP tool – guided session reset with compressed handoff
- [ ] Implement `get_tips()` MCP tool – active cost optimization recommendations

**Out of scope (Phase 4+):**
- Web dashboard
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

**Phase 3 (next):**
- [ ] Implement `engine/context_compressor.py` – session summary generation
- [ ] Implement `new_session()` MCP tool – guided session reset with compressed handoff
- [ ] Implement `get_tips()` MCP tool – active cost optimization recommendations

---

## Last updated

2026-04-10 – Auto-synced 1 commit(s) to 3740172
