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

Project filter selection now persists across page refresh via localStorage. Stored in `trace_selected_project`; auto-fallback to "All Projects" if stored project no longer exists.

---

## Last updated

2026-04-13 – Project filter persistence implemented (404 tests ✓)
