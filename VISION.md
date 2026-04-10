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

### Phase 1 – Foundation (MVP)
- `store.py` – SQLite-backed project and session store
- `log_session()` – manual token/cost logging per session
- `get_costs()` – cost report per project and total

### Phase 2 – Context Intelligence
- `git_watcher.py` – post-commit hook integration
- `doc_synthesizer.py` – automatic `AI_CONTEXT.md` generation and updates
- `update_context()` – MCP tool to trigger context refresh
- `check_drift()` – detects stale documentation

### Phase 3 – Optimization Layer
- `context_compressor.py` – session summary generation
- `new_session()` – guided session reset with compressed handoff. Directly addresses Claude Code's reactive Auto-Compact behaviour by giving developers proactive control over session boundaries and cost exposure.
- `get_tips()` – active cost optimization recommendations

### Phase 4 – Observability (future)
- Web dashboard (optional, local)
- Multi-MCP cost tracking via proxy layer
- Team/shared project support

## Why TRACE?

Because the best developers don't just write code – they operate systems. TRACE brings the same discipline of observability, documentation, and cost control to AI-assisted development that good engineers already apply everywhere else.

---

*TRACE is part of the same family as MindTrace – tools built by a practitioner, for practitioners.*
