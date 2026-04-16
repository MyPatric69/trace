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
464 tests green. Dashboard stable with day picker, provider badges,
persistent health indicator, enriched handoff prompt.
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
