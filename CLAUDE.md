# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> For full project context, always read `AI_CONTEXT.md` first – it is the authoritative re-entry point and replaces reading multiple separate docs.

## Project context

TRACE is an MCP server (Python / FastMCP) that provides token cost tracking and context intelligence for AI-assisted development.

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

**v0.3.0 released – v0.4.0 planning.**
554 tests green. Dashboard stable with day picker, provider badges,
persistent health indicator, enriched handoff prompt, activity stats,
52-week heatmap, context window utilization, monthly budget tracking.
Focus: Prometheus /metrics endpoint → Grafana integration.
Publish to Dev.to and Hacker News pending.

## Runtime Rules

- Never break existing tests – run pytest tests/ -v before committing
- AI_CONTEXT.md is auto-maintained by TRACE – do not edit manually
- Central DB: ~/.trace/trace.db – never delete or modify directly
- Config: ~/.trace/trace_config.yaml – source of truth for prices/thresholds
- Conventional Commits: feat/fix/docs/chore/refactor
- YAGNI, KISS, DRY, Single Responsibility

## Dev Commands

```bash
pytest tests/ -v          # run full test suite
bash dashboard/start.sh   # start dashboard → http://localhost:8080
python server/main.py     # start MCP server directly
```

## Dashboard Sections

Order (top to bottom):

1. Metrics cards – input / cache / output tokens, session cost, monthly budget %
2. Live Session – real-time token counts for the active session
3. Session Health – health bar + threshold markers; handoff link
4. Context Drift + Recommendations – drift status per project; smart cost tips
5. Activity – sessions, streaks, avg. cost/session, 52-week heatmap
6. Provider & Model Usage – provider badges + model cost bars, merged section
7. MCP Servers – registered servers + token-overhead estimate
8. Token Calculator – estimate cost before sending a prompt

## API Endpoints

```
GET  /api/status               – health, warn_tokens, critical_tokens, monthly_budget_usd
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
POST /api/live/clear
POST /api/settings             – accepts warn_tokens, critical_tokens, monthly_budget_usd (float, > 0)
GET  /api/tips                 ?project_name=
GET  /api/new_session/{project}  ?dry_run=
WS   /ws
```

## DB Schema

`sessions` table key columns:
- `peak_context_tokens` – highest context window usage recorded in the session

`TraceStore` methods of note:
- `get_activity_stats(project_id=None)` – returns session counts, streak data
- `get_heatmap_data(project_id=None)` – returns 52-week activity for heatmap
