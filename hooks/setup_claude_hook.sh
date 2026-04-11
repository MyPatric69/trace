#!/usr/bin/env bash
# TRACE – install SessionEnd and PostToolUse hooks into ~/.claude/settings.json
#
# Usage: bash hooks/setup_claude_hook.sh
# Run once. Idempotent – safe to run again if already installed.

set -euo pipefail

TRACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETTINGS="$HOME/.claude/settings.json"
# Quote paths so spaces are handled correctly by the shell
SESSION_END_CMD="python3 '${TRACE_ROOT}/engine/session_logger.py'"
POST_TOOL_CMD="python3 '${TRACE_ROOT}/engine/live_session_hook.py'"

python3 - "$SETTINGS" "$SESSION_END_CMD" "$POST_TOOL_CMD" <<'PYEOF'
import sys
import json
from pathlib import Path

settings_path = Path(sys.argv[1])
session_end_cmd = sys.argv[2]
post_tool_cmd  = sys.argv[3]

# Load or create settings
if settings_path.exists():
    with open(settings_path) as f:
        settings = json.load(f)
else:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings = {}

hooks = settings.setdefault("hooks", {})

# ── SessionEnd ──────────────────────────────────────────────────────────────
session_end = hooks.setdefault("SessionEnd", [])
se_installed = any(
    h.get("command") == session_end_cmd
    for matcher in session_end
    for h in matcher.get("hooks", [])
)
if se_installed:
    print("TRACE SessionEnd hook already installed.")
else:
    session_end.append({
        "matcher": "",
        "hooks": [{"type": "command", "command": session_end_cmd}]
    })
    print("TRACE SessionEnd hook installed in ~/.claude/settings.json")

# ── PostToolUse ─────────────────────────────────────────────────────────────
post_tool = hooks.setdefault("PostToolUse", [])
pt_installed = any(
    h.get("command") == post_tool_cmd
    for matcher in post_tool
    for h in matcher.get("hooks", [])
)
if pt_installed:
    print("TRACE PostToolUse hook already installed.")
else:
    post_tool.append({
        "matcher": "",
        "hooks": [{"type": "command", "command": post_tool_cmd}]
    })
    print("TRACE PostToolUse hook installed in ~/.claude/settings.json")

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
PYEOF
