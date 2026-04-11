#!/usr/bin/env bash
# TRACE – install SessionEnd hook into ~/.claude/settings.json
#
# Usage: bash hooks/setup_claude_hook.sh
# Run once. Idempotent – safe to run again if already installed.

set -euo pipefail

TRACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETTINGS="$HOME/.claude/settings.json"
HOOK_CMD="python3 $TRACE_ROOT/engine/session_logger.py"

python3 - "$SETTINGS" "$HOOK_CMD" <<'PYEOF'
import sys
import json
from pathlib import Path

settings_path = Path(sys.argv[1])
hook_cmd = sys.argv[2]

# Load or create settings
if settings_path.exists():
    with open(settings_path) as f:
        settings = json.load(f)
else:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings = {}

hooks = settings.setdefault("hooks", {})
session_end = hooks.setdefault("SessionEnd", [])

# Idempotency – skip if this command is already registered
for matcher in session_end:
    for h in matcher.get("hooks", []):
        if h.get("command") == hook_cmd:
            print("TRACE SessionEnd hook already installed.")
            sys.exit(0)

# Append new entry
session_end.append({
    "hooks": [{"type": "command", "command": hook_cmd}]
})

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print("TRACE SessionEnd hook installed in ~/.claude/settings.json")
PYEOF
