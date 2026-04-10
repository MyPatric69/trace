# trace

**Token-aware Realtime AI Context Engine** – an MCP server that tracks token costs and keeps `AI_CONTEXT.md` automatically current via git hook integration.

## Architecture

```
IDE Layer (Claude Code / Cursor / Codex)
    ↕ MCP protocol
MCP Server Core  [server/main.py – FastMCP]
    ↕ internal calls
Local Intelligence Engine  [engine/]
    ↕ read/write
Data Layer  [AI_CONTEXT.md · trace.db · trace_config.yaml]
```

Heavy computation runs locally (zero API cost). The MCP layer returns only compressed results.

## Why proactive session management?

Claude Code's Auto-Compact is **reactive** – it triggers at roughly 80–90% of the 200k token context window. By that point, cost per turn is already high and compounding.

TRACE takes a proactive approach using two thresholds in `trace_config.yaml`:

- **`warn_at_tokens: 30000`** – surfaces a warning early, before costs accelerate
- **`recommend_reset_at: 50000`** – recommends a session reset while context is still manageable

When a reset is appropriate, `new_session()` (Phase 3) compresses `AI_CONTEXT.md` into a clean re-entry prompt so the next session starts fully oriented – not blind.

The developer stays in control throughout. TRACE recommends; the developer decides.
