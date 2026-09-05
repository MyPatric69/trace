# SKILL.md – TRACE Specialized Workflows

## Session Lifecycle
- SessionEnd hook → session_logger.py → trace.db + DocSynthesizer
- Stop hook → live_session_hook.py → ~/.trace/live/{session_id}.json
- Status line bridge → ~/.claude/statusline_bridge.sh → /api/statusline

## Dashboard Development
- All UI changes in dashboard/index.html (single file)
- Backend in dashboard/server.py (FastAPI)
- Always reload dashboard after server.py changes

## Config Split
- trace_config.yaml (repo) = model prices, read-only at runtime
- ~/.trace/user_config.yaml = user preferences, written at runtime
- Never merge these two files

## Testing
- pytest tests/ -v before every commit
- No debug logging, no commented-out code
- One logical change per commit

## Git Workflow
- Conventional Commits: feat/fix/docs/chore/refactor
- Claude Code handles all git operations
- AI_CONTEXT.md is auto-committed by DocSynthesizer after each session
