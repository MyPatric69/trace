#!/usr/bin/env bash
# TRACE – install SessionEnd and Stop hooks into ~/.claude/settings.json
#
# Usage: bash hooks/setup_claude_hook.sh
# Run once. Idempotent – safe to run again if already installed.
#
# Note: Live token tracking uses the Stop hook (fires after every completed
# Claude response). PostToolUse was used in earlier versions but does not fire
# reliably in Claude Code Desktop App (Anthropic bug #42336).

set -euo pipefail

TRACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETTINGS="$HOME/.claude/settings.json"
# Quote paths so spaces are handled correctly by the shell
SESSION_END_CMD="python3 '${TRACE_ROOT}/engine/session_logger.py'"
STOP_CMD="python3 '${TRACE_ROOT}/engine/live_session_hook.py'"

python3 - "$SETTINGS" "$SESSION_END_CMD" "$STOP_CMD" <<'PYEOF'
import sys
import json
from pathlib import Path

settings_path = Path(sys.argv[1])
session_end_cmd = sys.argv[2]
stop_cmd        = sys.argv[3]
# Old PostToolUse command – remove if present (migration from earlier versions)
old_post_tool_cmd = stop_cmd.replace("live_session_hook", "live_session_hook")

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

# ── Migrate: remove our live_session_hook.py from PostToolUse if present ───
post_tool = hooks.get("PostToolUse", [])
new_post_tool = []
removed = 0
for matcher in post_tool:
    new_hooks = [
        h for h in matcher.get("hooks", [])
        if h.get("command") != stop_cmd
    ]
    removed += len(matcher.get("hooks", [])) - len(new_hooks)
    if new_hooks:
        new_post_tool.append({**matcher, "hooks": new_hooks})
    # else: drop the entire matcher block (it only had our hook)
if removed:
    print(f"Removed {removed} TRACE PostToolUse hook entry (migrated to Stop).")
if new_post_tool:
    hooks["PostToolUse"] = new_post_tool
elif "PostToolUse" in hooks and not new_post_tool:
    # All PostToolUse entries were ours – clean up the key
    if removed:
        del hooks["PostToolUse"]

# ── Stop ────────────────────────────────────────────────────────────────────
stop_list = hooks.setdefault("Stop", [])
stop_installed = any(
    h.get("command") == stop_cmd
    for matcher in stop_list
    for h in matcher.get("hooks", [])
)
if stop_installed:
    print("TRACE Stop hook already installed.")
else:
    stop_list.append({
        "matcher": "",
        "hooks": [{"type": "command", "command": stop_cmd}]
    })
    print("TRACE Stop hook installed in ~/.claude/settings.json")

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
PYEOF
