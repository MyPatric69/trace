# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> For full project context, always read `AI_CONTEXT.md` first – it is the authoritative re-entry point and replaces reading multiple separate docs.

## Project context

TRACE provides token cost tracking and context intelligence for AI-assisted development. Core features (hooks, dashboard, notifications, status line bridge) work standalone. The MCP server (Python / FastMCP) is an optional convenience layer for Claude Desktop users that exposes `new_session`, `check_drift`, `update_context`, `get_costs`, `log_session`, and `get_tips`.

## Working directory

/Users/patric/My AI Companion/github/trace

## Architecture

```
server/main.py              FastMCP entry point – registers 6 MCP tools
server/tools/costs.py       log_session(), get_costs()
server/tools/context.py     check_drift(), update_context()
server/tools/session.py     new_session(), get_tips()
engine/store.py             SQLite interface – the only layer that touches trace.db
engine/handoff_builder.py   build_handoff() – enriches new_session() prompt
engine/live_tracker.py      PostToolUse hook – incremental transcript parse → live_session.json
engine/live_session_hook.py Stop hook handler – fires after each completed response
engine/transcript_parser.py Shared transcript parsing (token counting)
engine/session_logger.py    SessionEnd hook – parses full transcript, logs to DB
dashboard/server.py         FastAPI web UI + REST + WebSocket endpoints
trace_config.yaml           Single source of truth: db path, model prices, budgets, health thresholds
```

**Data flow:** MCP tool call → `server/tools/*.py` → `engine/store.py` → `trace.db`. Tools never query SQLite directly; they go through `TraceStore`.

## Current Phase

**All phases complete – 606 tests green.**
Dashboard stable: stale session indicator ("paused X min ago", 5-min threshold),
context window utilization bar (peak = max(input + cache_creation + cache_read) per turn),
day picker, provider badges, persistent health indicator, enriched handoff prompt,
activity stats, 52-week heatmap, monthly budget tracking, cost efficiency panel.

**Health signal:** notifications and the `Request new_session()` handoff button are driven by
`context_window_pct` (defaults: warn 60 %, critical 85 %) – the quality signal sourced
from the Claude Code status line. Cumulative tokens (`warn_tokens` / `critical_tokens`)
remain in `session_health` config for backward compat but no longer drive any UI –
the dedicated **Session Cost** panel was removed; cumulative session tokens are now
shown as a muted info row inside the **Live Session** panel.

## Runtime Rules

- Never break existing tests – run pytest tests/ -v before committing
- AI_CONTEXT.md is auto-maintained by TRACE – do not edit manually
- Central DB: ~/.trace/trace.db – never delete or modify directly
- Config: `trace_config.yaml` (repo root, model prices – read-only) + `~/.trace/user_config.yaml` (thresholds, budget, notifications – written at runtime)
- Conventional Commits: feat/fix/docs/chore/refactor
- YAGNI, KISS, DRY, Single Responsibility

## Dev Commands

```bash
pytest tests/ -v          # run full test suite
bash dashboard/start.sh   # start dashboard → http://localhost:8080
python server/main.py     # start MCP server directly
```

## Hooks

```
hooks/statusline_bridge.sh        reads Claude Code JSON from stdin, POSTs to /api/statusline, outputs status line to terminal
hooks/setup_statusline_bridge.sh  installs bridge to ~/.claude/statusline_bridge.sh; adds statusLine config to ~/.claude/settings.json (idempotent)
hooks/remove_statusline_bridge.sh removes statusLine config from settings.json; deletes bridge script
hooks/post-commit                 git post-commit → engine/hook_runner.run() → DocSynthesizer.update_if_stale()
```

**Hook → AI_CONTEXT.md refresh chain:**
- **post-commit hook** → `engine/hook_runner.run()` → `DocSynthesizer.update_if_stale()`
- **SessionEnd hook** → `engine/session_logger.run()` → `add_session()` → `DocSynthesizer.update_if_stale()`

Both paths share the same logic: rewrite `AI_CONTEXT.md` only when there are doc-relevant changes since `.trace_sync`, or when `AI_CONTEXT.md` is older than 2 days (`DocSynthesizer._STALE_DAYS`). Synthesizer failures are caught and logged – they never break the commit or the session log.

## trace.sh Menu

| # | Option |
|---|---|
| 1 | Install TRACE (MCP server NOT installed automatically) |
| 2 | Add project |
| 3 | Update TRACE |
| 4 | Remove project |
| 5 | Uninstall TRACE |
| 6 | Exit |
| 7 | Setup status line bridge |
| 8 | Remove status line bridge |
| 9 | Setup MCP server (optional – Claude Desktop only) |
| 10 | Remove MCP server |

## Dashboard Sections

Order (top to bottom):

1. Metrics cards – input / cache / output tokens, session cost, monthly budget %
2. Live Session – real-time token counts for the active session, including a Tokens row (`{total} total · Turn N`) below Changes. Handoff link lives inside the Context Window bar, shown when `context_window_pct >= warn_context_pct`.
3. Context Drift + Recommendations – drift status per project; smart cost tips
4. Activity – sessions, streaks, avg. cost/session, 52-week heatmap
5. Cost Efficiency – actual vs. baseline-model cost
6. Provider & Model Usage – provider badges + model cost bars, merged section
7. MCP Servers – registered servers + token-overhead estimate
8. Token Calculator – estimate cost before sending a prompt

## API Endpoints

```
GET  /api/status               – health, warn_context_pct, critical_context_pct, monthly_budget_usd, baseline_model
GET  /api/projects
GET  /api/costs                ?period=
GET  /api/costs/{project}      ?period=
GET  /api/tokens               ?project= &period=
GET  /api/stats/{date}         ?project=
GET  /api/today                ?project=
GET  /api/models               ?period= &project=
GET  /api/providers
GET  /api/provider             ?period=
GET  /api/drift/{project}
GET  /api/sync/{project}
GET  /api/live                 ?project=
GET  /api/activity             – activity stats and 52-week heatmap
GET  /api/efficiency           ?project= &period= – actual vs. baseline cost
GET  /api/tokenizer_ratio      – ratio of current model tokens vs. baseline
POST /api/live/clear
POST /api/statusline           – receives status line data from bridge; updates live session context_window_pct and cost in real-time
POST /api/settings             – accepts warn_tokens, critical_tokens, warn_context_pct, critical_context_pct, monthly_budget_usd, baseline_model
GET  /api/tips                 ?project_name=
GET  /api/new_session/{project}  ?dry_run=
WS   /ws
```

## DB Schema

`sessions` table key columns:
- `peak_context_tokens` – peak context load per turn: max(input_tokens + cache_creation_input_tokens + cache_read_input_tokens) across all turns

`TraceStore` methods of note:
- `get_activity_stats(project_id=None)` – returns session counts, streak data
- `get_heatmap_data(project_id=None)` – returns 52-week activity for heatmap

## ThreadBridge — Inter-Session Communication

This project uses ThreadBridge for async messaging between Claude Code sessions.

### Session Start
At the start of every session, read pending messages:
read_messages(topic="collab/trace/insights")
read_messages(topic="collab/trace/decisions")
read_messages(topic="collab/trace/tasks")

### Session End
Before ending a session, write a changelog entry:

from threadbridge import CollabPayload
from threadbridge.store import MessageStore
from threadbridge.config import DB_PATH

store = MessageStore(DB_PATH)
p = CollabPayload(
    type="changelog",
    from_session="trace",
    content="## Session <datum>\n- <was wurde gemacht>",
    confidence="high"
)
store.send(topic="collab/trace/changelog", payload=p.to_json(), sender="trace")

### Topic Schema
- collab/trace/tasks      — offene Aufgaben
- collab/trace/insights   — Erkenntnisse
- collab/trace/decisions  — Entscheidungen
- collab/trace/changelog  — Session-Protokoll
