#!/bin/bash
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(which python3)"
PLIST="$HOME/Library/LaunchAgents/com.trace.dashboard.plist"
LOG="$HOME/.trace/dashboard.log"

mkdir -p "$HOME/.trace"
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.trace.dashboard</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>dashboard.server:app</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8080</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$REPO_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG</string>
  <key>StandardErrorPath</key>
  <string>$LOG</string>
</dict>
</plist>
EOF

launchctl load "$PLIST"

echo "TRACE dashboard autostart enabled."
echo "  URL: http://localhost:8080"
echo "  Log: $LOG"
echo "  To disable: bash hooks/remove_dashboard_autostart.sh"
