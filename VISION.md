# TRACE – Vision

**Token-aware Realtime AI Context Engine**

## The Problem

Modern AI-assisted development creates two invisible problems nobody talks about:

1. **Token cost drift** – Every message in a long chat re-sends the entire conversation history as input tokens. A session that starts at $0.01 per turn ends at $0.50 per turn. Nobody tracks this. Nobody notices until the bill arrives.

2. **Context rot** – Project documentation (ARCHITECTURE.md, JOURNAL.md, LEARNINGS.md) goes stale within hours of active development. The AI re-enters every session blind, wasting tokens re-establishing context that should already be there.

## The Solution

TRACE is an MCP server that runs locally on your machine and integrates directly into your AI development environment (Claude Code, Cursor, Codex). It acts as a **permanent project intelligence layer** – always aware, always current, zero API cost for the heavy work.

TRACE solves both problems simultaneously:
- It keeps a compressed, token-optimized `AI_CONTEXT.md` per project, updated automatically on every git commit
- It tracks token consumption and costs across all sessions, per project, with budget alerts

## Core Principles

**Local-heavy, API-light.** All file watching, git analysis, doc synthesis, and cost aggregation runs locally in Python. The MCP interface returns only compressed results – never raw data.

**Delta-based updates.** TRACE never rewrites documentation from scratch. It analyses git diffs and applies targeted updates – fast, cheap, precise.

**Self-documenting.** TRACE maintains its own `AI_CONTEXT.md`. It eats its own cooking.

**Convention over configuration.** Sensible defaults out of the box. One config file (`trace_config.yaml`) for everything that needs customization.

**Open and extensible.** MIT licensed. Built to be forked, extended, and integrated.

## Target Users

Developers who use AI coding assistants daily and want to stop hemorrhaging tokens on context that should already be there.

## Roadmap

### v0.1.0 (complete)
- 6 MCP tools: `log_session`, `get_costs`, `check_drift`, `update_context`, `new_session`, `get_tips`
- Local web dashboard at http://localhost:8080
- Git hook auto-updates `AI_CONTEXT.md` on every commit
- `SessionEnd` hook auto-logs token usage
- Central `~/.trace/` database for all projects
- Global git template – zero setup per project

### v0.2.0 (planned)
Four features in priority order:

1. **Config Auto-Sync**
   - Store reads `~/.trace/trace_config.yaml` first, falls back to project `trace_config.yaml`
   - `setup_global_template.sh` syncs config automatically
   - Eliminates dual-config technical debt

2. **Live Token Tracking**
   - `PostToolUse` hook reads `transcript.jsonl` after every tool call
   - Writes to `~/.trace/live_session.json`
   - New `/api/live` endpoint in dashboard
   - Dashboard refreshes live panel every 5 seconds
   - Proactive session management – no need to end session to see current token count

3. **Provider-agnostic API Integration**
   - Abstract provider interface in `engine/providers/`
   - Adapters: `anthropic`, `openai`, `vertexai`, `manual`
   - Credential sources: env, keychain, file
   - Budget tracking where provider supports quotas
   - Dashboard shows "no quota configured" when provider returns no budget data
   - Extensible: new providers via PR

4. **WebSocket Push**
   - Replace polling with WebSocket push
   - Dashboard updates instantly when DB changes
   - No more 30s delay after session end

### v0.3.0 (ideas)
- Team/shared project support
- CI/CD pipeline integration
- Export costs as CSV/PDF report
- Slack/email alerts for budget thresholds

## Why TRACE?

Because the best developers don't just write code – they operate systems. TRACE brings the same discipline of observability, documentation, and cost control to AI-assisted development that good engineers already apply everywhere else.

---

*TRACE is part of the same family as MindTrace – tools built by a practitioner, for practitioners.*
