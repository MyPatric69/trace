#!/usr/bin/env bash
# TRACE – install the status line bridge into ~/.claude/
#
# Usage: bash hooks/setup_statusline_bridge.sh
# Idempotent – safe to run again if already installed.

set -euo pipefail

TRACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRIDGE_SRC="$TRACE_ROOT/hooks/statusline_bridge.sh"
BRIDGE_DST="$HOME/.claude/statusline_bridge.sh"
SETTINGS="$HOME/.claude/settings.json"

# ── Copy and mark executable ──────────────────────────────────────────────────
mkdir -p "$HOME/.claude"
cp "$BRIDGE_SRC" "$BRIDGE_DST"
chmod +x "$BRIDGE_DST"
echo "Copied statusline_bridge.sh → $BRIDGE_DST"

# ── Merge statusLine config into settings.json ────────────────────────────────
python3 - "$SETTINGS" "$BRIDGE_DST" <<'PYEOF'
import sys
import json
from pathlib import Path

settings_path = Path(sys.argv[1])
bridge_path   = sys.argv[2]

if settings_path.exists():
    with open(settings_path) as f:
        settings = json.load(f)
else:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings = {}

if settings.get("statusLine") == {"type": "command", "command": bridge_path}:
    print("TRACE status line bridge already configured.")
else:
    settings["statusLine"] = {"type": "command", "command": bridge_path}
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("TRACE status line bridge added to ~/.claude/settings.json")
PYEOF

echo ""
echo "Done.  The status line will appear after every Claude Code response."
echo "Requires jq – install once with:  brew install jq"
