#!/bin/bash
# Wrapper for engine/tokenizer_check.py – resolves ANTHROPIC_API_KEY from
# macOS Keychain before calling the script, since LaunchAgents don't inherit
# shell environment variables.

export PATH="/Users/patric/.pyenv/shims:/Users/patric/.pyenv/bin:$PATH"
eval "$(pyenv init -)" 2>/dev/null || true

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON=$(pyenv which python3 2>/dev/null || which python3)

# 1. Try the dedicated ANTHROPIC_API_KEY keychain entry
KEY=$(security find-generic-password -s "ANTHROPIC_API_KEY" -w 2>/dev/null)

# 2. Fall back to the Claude Code keychain entry
if [ -z "$KEY" ]; then
  KEY=$(security find-generic-password -s "claude" -a "api_key" -w 2>/dev/null)
fi

if [ -z "$KEY" ]; then
  echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") ERROR: ANTHROPIC_API_KEY not found in Keychain." >&2
  echo "Store it with:" >&2
  echo "  security add-generic-password -s ANTHROPIC_API_KEY -a anthropic -w sk-ant-..." >&2
  exit 1
fi

export ANTHROPIC_API_KEY="$KEY"
exec "$PYTHON" "$REPO_DIR/engine/tokenizer_check.py"
