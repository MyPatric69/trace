#!/bin/bash
set -e

PLIST="$HOME/Library/LaunchAgents/com.trace.dashboard.plist"

if [ ! -f "$PLIST" ]; then
  echo "LaunchAgent not found – nothing to remove."
  exit 0
fi

launchctl unload "$PLIST"
rm "$PLIST"

echo "TRACE dashboard autostart disabled."
