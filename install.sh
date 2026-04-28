#!/bin/bash
# TRACE unified installer – auto-detects situation and guides through setup.
# Usage: bash install.sh (run from the TRACE repo or any project directory)
# macOS only. No sudo required.

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}✅ $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠️  $*${RESET}"; }
err()  { echo -e "${RED}❌ $*${RESET}"; exit 1; }
step() { echo -e "${BOLD}→ $*${RESET}"; }

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$PWD"

# ── Version ───────────────────────────────────────────────────────────────────
TRACE_VERSION="$(grep 'version:' "$SCRIPT_DIR/trace_config.yaml" | head -1 | awk '{print $2}')"

# ── Detection ─────────────────────────────────────────────────────────────────
TRACE_INSTALLED=false
[[ -f "$HOME/.trace/user_config.yaml" ]] && TRACE_INSTALLED=true

IN_TRACE_REPO=false
[[ "$PROJECT_DIR" == "$SCRIPT_DIR" ]] && IN_TRACE_REPO=true

IN_PROJECT=false
if [[ "$PROJECT_DIR" != "$SCRIPT_DIR" ]] && { [[ -f "$PROJECT_DIR/CLAUDE.md" ]] || [[ -d "$PROJECT_DIR/.git" ]]; }; then
  IN_PROJECT=true
fi

# ── Helpers ───────────────────────────────────────────────────────────────────
check_prerequisites() {
  step "Checking prerequisites..."

  if ! command -v python3 &>/dev/null; then
    err "python3 not found. Install via Homebrew: brew install python3"
  fi
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    err "Python 3.10+ required. Found: $(python3 --version). Upgrade via: brew install python3"
  fi
  echo "  python3: $(python3 --version)"

  if ! python3 -m pip --version &>/dev/null 2>&1; then
    err "pip not found. Run: python3 -m ensurepip --upgrade"
  fi
  echo "  pip: ok"

  if ! command -v git &>/dev/null; then
    err "git not found. Run: xcode-select --install"
  fi
  echo "  git: $(git --version)"

  ok "Prerequisites satisfied"
}

check_api_key() {
  step "Checking ANTHROPIC_API_KEY in Keychain..."
  if security find-generic-password -s "ANTHROPIC_API_KEY" -w &>/dev/null 2>&1; then
    ok "ANTHROPIC_API_KEY found in Keychain"
  else
    warn "ANTHROPIC_API_KEY not found in Keychain. Add it with:"
    echo "    security add-generic-password -s ANTHROPIC_API_KEY -a anthropic -w sk-ant-..."
    echo "  (You can add it later – continuing)"
  fi
}

install_deps() {
  step "Installing Python dependencies..."
  pip3 install -r "$SCRIPT_DIR/requirements.txt" --break-system-packages -q \
    2>/dev/null || pip3 install -r "$SCRIPT_DIR/requirements.txt" -q
  ok "Dependencies installed"
}

init_trace() {
  step "Initializing TRACE data directory..."
  mkdir -p "$HOME/.trace"

  if [[ ! -f "$HOME/.trace/trace_config.yaml" ]]; then
    cp "$SCRIPT_DIR/trace_config.yaml" "$HOME/.trace/trace_config.yaml"
  fi

  python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from engine.store import TraceStore
store = TraceStore.default()
store.init_db()
print('  DB:', store.db_path)
"
  ok "TRACE initialized at ~/.trace/"
}

register_project() {
  local path="$1"
  local name
  name="$(basename "$path")"

  step "Registering project '$name'..."
  python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from engine.store import TraceStore
store = TraceStore.default()
store.init_db()
try:
    store.add_project('$name', '$path', '')
    print('  Registered: $name')
except Exception as e:
    if 'UNIQUE constraint' in str(e):
        print('  Already registered: $name')
    else:
        raise
"
}

reload_agent() {
  local label="$1"
  local plist="$HOME/Library/LaunchAgents/${label}.plist"
  if [[ -f "$plist" ]]; then
    launchctl unload "$plist" 2>/dev/null || true
    launchctl load "$plist"
    echo "  Reloaded: $label"
  else
    warn "$label plist not found – run setup scripts first"
  fi
}

# ── Mode 1: Fresh install ─────────────────────────────────────────────────────
mode_fresh_install() {
  echo ""
  echo -e "${BOLD}TRACE v${TRACE_VERSION} – Fresh install${RESET}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  check_prerequisites
  check_api_key
  install_deps
  init_trace

  step "Installing Claude Code hooks..."
  bash "$SCRIPT_DIR/hooks/setup_claude_hook.sh"
  ok "Claude Code hooks installed"

  step "Setting up dashboard autostart..."
  bash "$SCRIPT_DIR/hooks/setup_dashboard_autostart.sh"

  step "Setting up tokenizer check..."
  bash "$SCRIPT_DIR/hooks/setup_tokenizer_check.sh"

  if [[ "$IN_PROJECT" == true ]]; then
    register_project "$PROJECT_DIR"
    if [[ -d "$PROJECT_DIR/.git" ]]; then
      step "Installing git hook in project..."
      bash "$SCRIPT_DIR/hooks/install_hook.sh" "$PROJECT_DIR"
    fi
  fi

  echo ""
  ok "TRACE installed successfully"
  echo ""
  echo "  Dashboard: http://localhost:8080"
  echo "  Restart Claude Desktop to activate the MCP server"
  echo "  Next: open a Claude Code session to start tracking"
  echo ""
}

# ── Mode 2: Add project ───────────────────────────────────────────────────────
mode_add_project() {
  local name
  name="$(basename "$PROJECT_DIR")"

  echo ""
  echo -e "${BOLD}TRACE v${TRACE_VERSION} – Add project${RESET}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  if ! [[ -f "$PROJECT_DIR/CLAUDE.md" ]] && ! [[ -d "$PROJECT_DIR/.git" ]]; then
    warn "Current directory ('$PROJECT_DIR') does not look like a project."
    warn "Run install.sh from a directory that contains a CLAUDE.md or .git folder."
    exit 1
  fi

  step "Adding project '$name' to TRACE..."

  step "Verifying Claude Code hooks (idempotent)..."
  bash "$SCRIPT_DIR/hooks/setup_claude_hook.sh"

  register_project "$PROJECT_DIR"

  if [[ -d "$PROJECT_DIR/.git" ]]; then
    if [[ ! -f "$PROJECT_DIR/.git/hooks/post-commit" ]]; then
      step "Installing git hook..."
      bash "$SCRIPT_DIR/hooks/install_hook.sh" "$PROJECT_DIR"
    else
      echo "  Git hook already installed"
    fi
  fi

  echo ""
  ok "Project '$name' added to TRACE"
  echo "  Start a Claude Code session here to begin tracking"
  echo ""
}

# ── Mode 3: Update ────────────────────────────────────────────────────────────
mode_update() {
  echo ""
  echo -e "${BOLD}TRACE v${TRACE_VERSION} – Update${RESET}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  step "Pulling latest changes..."
  git -C "$SCRIPT_DIR" pull origin main

  step "Updating Python dependencies..."
  pip3 install -r "$SCRIPT_DIR/requirements.txt" --break-system-packages -q \
    2>/dev/null || pip3 install -r "$SCRIPT_DIR/requirements.txt" -q
  ok "Dependencies updated"

  step "Reloading LaunchAgents..."
  reload_agent "com.trace.dashboard"
  reload_agent "com.trace.tokenizer"

  echo ""
  ok "TRACE updated to latest version"
  echo "  User settings preserved in ~/.trace/user_config.yaml"
  echo ""
}

# ── Full reinstall ────────────────────────────────────────────────────────────
mode_reinstall() {
  echo ""
  echo -e "${BOLD}TRACE – Full reinstall (preserving user settings)${RESET}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  local backup=""
  if [[ -f "$HOME/.trace/user_config.yaml" ]]; then
    backup="/tmp/trace_user_config_backup.yaml"
    cp "$HOME/.trace/user_config.yaml" "$backup"
    echo "  User config backed up to $backup"
  fi

  install_deps
  init_trace

  if [[ -n "$backup" ]] && [[ -f "$backup" ]]; then
    cp "$backup" "$HOME/.trace/user_config.yaml"
    rm -f "$backup"
    echo "  User settings restored"
  fi

  step "Re-installing Claude Code hooks..."
  bash "$SCRIPT_DIR/hooks/setup_claude_hook.sh"

  step "Re-installing dashboard autostart..."
  bash "$SCRIPT_DIR/hooks/setup_dashboard_autostart.sh"

  step "Re-installing tokenizer check..."
  bash "$SCRIPT_DIR/hooks/setup_tokenizer_check.sh"

  echo ""
  ok "TRACE reinstalled"
  echo "  User settings preserved in ~/.trace/user_config.yaml"
  echo ""
}

# ── Menu (installed + in TRACE repo) ─────────────────────────────────────────
show_menu() {
  echo ""
  echo -e "${BOLD}TRACE v${TRACE_VERSION} is already installed.${RESET}"
  echo ""
  echo "What would you like to do?"
  echo "  1) Add current directory as new project"
  echo "  2) Update TRACE to latest version"
  echo "  3) Full reinstall (preserves user settings)"
  echo "  4) Exit"
  echo ""
  read -r -p "Choice [1-4]: " choice

  case "$choice" in
    1) mode_add_project ;;
    2) mode_update ;;
    3) mode_reinstall ;;
    4) echo "Exiting."; exit 0 ;;
    *) err "Invalid choice: $choice" ;;
  esac
}

# ── Main dispatch ─────────────────────────────────────────────────────────────
if [[ "$TRACE_INSTALLED" == false ]]; then
  mode_fresh_install
elif [[ "$IN_TRACE_REPO" == true ]]; then
  show_menu
else
  mode_add_project
fi
