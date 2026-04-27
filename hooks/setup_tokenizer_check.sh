#!/bin/bash
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(which python3)"
PLIST="$HOME/Library/LaunchAgents/com.trace.tokenizer.plist"
LOG="$HOME/.trace/tokenizer_check.log"

mkdir -p "$HOME/.trace"
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.trace.tokenizer</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$REPO_DIR/engine/tokenizer_check_wrapper.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$REPO_DIR</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>7</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG</string>
  <key>StandardErrorPath</key>
  <string>$LOG</string>
</dict>
</plist>
EOF

launchctl load "$PLIST"

echo "TRACE tokenizer check LaunchAgent installed."
echo "  Runs:   daily at 07:00"
echo "  Log:    $LOG"
echo "  Output: $HOME/.trace/tokenizer_ratio.json"
echo "  To remove: bash hooks/remove_tokenizer_check.sh"
