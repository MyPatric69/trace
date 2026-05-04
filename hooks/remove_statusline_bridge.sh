#!/usr/bin/env bash
# TRACE – remove the status line bridge from ~/.claude/
#
# Usage: bash hooks/remove_statusline_bridge.sh

set -euo pipefail

BRIDGE_DST="$HOME/.claude/statusline_bridge.sh"
SETTINGS="$HOME/.claude/settings.json"

# ── Remove statusLine key from settings.json ──────────────────────────────────
if [ -f "$SETTINGS" ]; then
    python3 - "$SETTINGS" <<'PYEOF'
import sys
import json
from pathlib import Path

settings_path = Path(sys.argv[1])
with open(settings_path) as f:
    settings = json.load(f)

if "statusLine" in settings:
    del settings["statusLine"]
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("Removed statusLine config from ~/.claude/settings.json")
else:
    print("statusLine config not found – nothing to remove.")
PYEOF
else
    echo "~/.claude/settings.json not found – nothing to update."
fi

# ── Delete bridge script ──────────────────────────────────────────────────────
if [ -f "$BRIDGE_DST" ]; then
    rm "$BRIDGE_DST"
    echo "Deleted $BRIDGE_DST"
else
    echo "$BRIDGE_DST not found – nothing to delete."
fi

echo "TRACE status line bridge removed."
