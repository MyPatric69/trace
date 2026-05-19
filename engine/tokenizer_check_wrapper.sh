#!/bin/bash
# Wrapper for engine/tokenizer_check.py – loads credentials from .env since
# LaunchAgents don't inherit shell environment variables.

export PATH="/Users/patric/.pyenv/shims:/Users/patric/.pyenv/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYENV_ROOT="/Users/patric/.pyenv"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="/Users/patric/.pyenv/versions/3.12.9/bin/python3"
if [ ! -f "$PYTHON" ]; then
  PYTHON=$(which python3)
fi

# Load credentials from .env (not committed to git)
if [ -f "$REPO_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_DIR/.env"
  set +a
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") ERROR: ANTHROPIC_API_KEY not set." >&2
  echo "Add it to $REPO_DIR/.env" >&2
  exit 1
fi

exec "$PYTHON" "$REPO_DIR/engine/tokenizer_check.py"
