#!/bin/bash
# trace.sh – TRACE lifecycle manager
# Usage:
#   bash trace.sh                          # interactive menu
#   bash trace.sh install                  # install TRACE
#   bash trace.sh add [path]               # add project to TRACE
#   bash trace.sh remove [path]            # remove project from TRACE
#   bash trace.sh update                   # update TRACE
#   bash trace.sh uninstall                # uninstall TRACE
# macOS only. No sudo required.

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}✅ $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠️  $*${RESET}"; }
err()  { echo -e "${RED}❌ $*${RESET}"; exit 1; }
step() { echo -e "${BOLD}→ $*${RESET}"; }

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Version ───────────────────────────────────────────────────────────────────
TRACE_VERSION="$(grep 'version:' "$SCRIPT_DIR/trace_config.yaml" | head -1 | awk '{print $2}')"

# ── Detection ─────────────────────────────────────────────────────────────────
TRACE_INSTALLED=false
[[ -f "$HOME/.trace/user_config.yaml" ]] && TRACE_INSTALLED=true

# ── Header ────────────────────────────────────────────────────────────────────
show_header() {
  local ver_line="   TRACE Manager v${TRACE_VERSION}"
  local sub_line="   Token-Aware AI Context Engine"
  local w=42
  local ver_pad sub_pad
  ver_pad=$(( w - ${#ver_line} ))
  sub_pad=$(( w - ${#sub_line} ))

  echo ""
  echo -e "${BOLD}╔══════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}║${RESET}${GREEN}${ver_line}$(printf '%*s' $ver_pad '')${RESET}${BOLD}║${RESET}"
  echo -e "${BOLD}║${RESET}${sub_line}$(printf '%*s' $sub_pad '')${BOLD}║${RESET}"
  echo -e "${BOLD}╚══════════════════════════════════════════╝${RESET}"
  echo ""
}

# ── Path prompt helper ────────────────────────────────────────────────────────
PROMPTED_PATH=""

_normalize_path() {
  local p="$1"
  # Resolve backslash-escaped spaces (Tab-completed paths)
  p="$(eval echo "$p")"
  # Strip trailing slash
  p="${p%/}"
  echo "$p"
}

prompt_project_path() {
  local attempt=0 raw_path resolved
  PROMPTED_PATH=""
  while [[ $attempt -lt 3 ]]; do
    if ! read -e -r -p "  Project path (absolute or relative): " raw_path; then
      raw_path=""
    fi
    raw_path="$(_normalize_path "$raw_path")"
    raw_path="${raw_path/#\~/$HOME}"
    resolved="$(realpath "$raw_path" 2>/dev/null || echo "")"
    if [[ -n "$resolved" ]] && { [[ -f "$resolved/CLAUDE.md" ]] || [[ -d "$resolved/.git" ]]; }; then
      PROMPTED_PATH="$resolved"
      return 0
    fi
    warn "Not a valid project directory (needs CLAUDE.md or .git): ${raw_path:-<empty>}"
    (( attempt++ ))
  done
  err "Max attempts reached. Provide a directory containing CLAUDE.md or .git."
}

resolve_path_arg() {
  local path="$1"
  path="$(_normalize_path "$path")"
  path="${path/#\~/$HOME}"
  local resolved
  resolved="$(realpath "$path" 2>/dev/null || echo "")"
  if [[ -z "$resolved" ]] || ! { [[ -f "$resolved/CLAUDE.md" ]] || [[ -d "$resolved/.git" ]]; }; then
    err "Not a valid project directory (needs CLAUDE.md or .git): $path"
  fi
  echo "$resolved"
}

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

# ── Option 1 – Install ────────────────────────────────────────────────────────
mode_fresh_install() {
  echo ""
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "${BOLD} Option 1 – Install TRACE${RESET}"
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
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

  echo ""
  ok "TRACE installed successfully"
  echo ""
  echo "  Dashboard: http://localhost:8080"
  echo "  Restart Claude Desktop to activate the MCP server"
  echo "  Next: run 'bash trace.sh add <path>' to register a project"
  echo ""
}

# ── Option 2 – Add project ────────────────────────────────────────────────────
mode_add_project() {
  local target_path="${1:-}"

  echo ""
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "${BOLD} Option 2 – Add project to TRACE${RESET}"
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo ""

  warn "Make sure you have run 'claude /init' or 'git init' in the project directory first."
  echo ""

  if [[ -z "$target_path" ]]; then
    prompt_project_path
    target_path="$PROMPTED_PATH"
  else
    target_path="$(resolve_path_arg "$target_path")"
  fi

  local name
  name="$(basename "$target_path")"

  step "Adding project '$name' to TRACE..."

  step "Verifying Claude Code hooks (idempotent)..."
  bash "$SCRIPT_DIR/hooks/setup_claude_hook.sh"

  register_project "$target_path"

  if [[ -d "$target_path/.git" ]]; then
    if [[ ! -f "$target_path/.git/hooks/post-commit" ]]; then
      step "Installing git hook..."
      bash "$SCRIPT_DIR/hooks/install_hook.sh" "$target_path"
    else
      echo "  Git hook already installed"
    fi
  fi

  echo ""
  ok "Project '$name' added to TRACE"
  echo "  Start a Claude Code session here to begin tracking"
  echo ""
}

# ── Option 3 – Update ─────────────────────────────────────────────────────────
mode_update() {
  local version_before="$TRACE_VERSION"

  echo ""
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "${BOLD} Option 3 – Update TRACE${RESET}"
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo ""

  step "Pulling latest changes..."
  local pull_output
  pull_output="$(git -C "$SCRIPT_DIR" pull origin main 2>&1)"
  echo "$pull_output"

  step "Updating Python dependencies..."
  pip3 install -r "$SCRIPT_DIR/requirements.txt" --break-system-packages -q \
    2>/dev/null || pip3 install -r "$SCRIPT_DIR/requirements.txt" -q
  ok "Dependencies updated"

  step "Reloading LaunchAgents..."
  reload_agent "com.trace.dashboard"
  reload_agent "com.trace.tokenizer"

  local version_after
  version_after="$(grep 'version:' "$SCRIPT_DIR/trace_config.yaml" | head -1 | awk '{print $2}')"

  echo ""
  if echo "$pull_output" | grep -q "Already up to date"; then
    ok "Already on latest version (v${version_after})"
  else
    ok "Updated from v${version_before} to v${version_after} – user data preserved"
  fi
  echo ""
}

# ── Option 4 – Remove project ─────────────────────────────────────────────────
mode_remove_project() {
  local target_path="${1:-}"

  echo ""
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "${BOLD} Option 4 – Remove project${RESET}"
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo ""

  if [[ -z "$target_path" ]]; then
    prompt_project_path
    target_path="$PROMPTED_PATH"
  else
    target_path="$(resolve_path_arg "$target_path")"
  fi

  local name
  name="$(basename "$target_path")"

  echo -e "  Project: ${BOLD}'${name}'${RESET} (${target_path})"
  echo ""

  local confirm
  read -r -p "  Remove TRACE from '${name}'? [y/N] " confirm || true

  if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "  Cancelled."
    exit 0
  fi

  if [[ -f "$target_path/.git/hooks/post-commit" ]]; then
    step "Removing git hook..."
    rm -f "$target_path/.git/hooks/post-commit"
    echo "  Removed: .git/hooks/post-commit"
  else
    echo "  No git hook found in .git/hooks/"
  fi

  step "Unregistering project from TRACE..."
  python3 -c "
import sys, sqlite3
sys.path.insert(0, '$SCRIPT_DIR')
from engine.store import TraceStore
store = TraceStore.default()
conn = sqlite3.connect(store.db_path)
conn.execute('DELETE FROM projects WHERE name = ?', ('$name',))
conn.commit()
conn.close()
print('  Unregistered: $name')
" 2>/dev/null || echo "  Project not found in DB (already removed)"

  echo ""
  ok "TRACE removed from '${name}'"
  echo "  Session data in trace.db is preserved"
  echo ""
}

# ── Option 5 – Uninstall ──────────────────────────────────────────────────────
mode_uninstall() {
  echo ""
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "${BOLD} Option 5 – Uninstall TRACE${RESET}"
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo ""
  echo -e "${YELLOW}${BOLD}⚠️  This will remove:${RESET}"
  echo    "   • All LaunchAgents (dashboard + tokenizer)"
  echo    "   • MCP server entry from Claude Desktop config"
  echo    "   • ~/.trace/ directory (including trace.db and all session data)"
  echo    "   • Git hooks from all registered projects"
  echo    "   Your TRACE repo will NOT be deleted."
  echo ""

  local confirm
  read -r -p "  Type 'uninstall' to confirm: " confirm || true

  if [[ "$confirm" != "uninstall" ]]; then
    echo "  Cancelled."
    exit 0
  fi

  echo ""

  # Collect registered project paths before deleting the DB
  local proj_paths=()
  if [[ -f "$HOME/.trace/trace.db" ]]; then
    while IFS= read -r proj_path; do
      [[ -n "$proj_path" ]] && proj_paths+=("$proj_path")
    done < <(python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from engine.store import TraceStore
store = TraceStore.default()
for p in store.list_projects():
    print(p.get('path', ''))
" 2>/dev/null || true)
  fi

  # Remove git hooks from all registered projects
  if [[ ${#proj_paths[@]} -gt 0 ]]; then
    step "Removing git hooks from registered projects..."
    for proj_path in "${proj_paths[@]}"; do
      local hook_file="${proj_path}/.git/hooks/post-commit"
      if [[ -f "$hook_file" ]]; then
        rm -f "$hook_file"
        echo "  Removed hook from: $proj_path"
      fi
    done
  fi

  # Unload and remove LaunchAgents
  step "Removing LaunchAgents..."
  for label in "com.trace.dashboard" "com.trace.tokenizer"; do
    local plist="$HOME/Library/LaunchAgents/${label}.plist"
    if [[ -f "$plist" ]]; then
      launchctl unload "$plist" 2>/dev/null || true
      rm -f "$plist"
      echo "  Removed: $label"
    else
      echo "  Not found: $label (skipped)"
    fi
  done

  # Remove MCP entry from Claude Desktop config
  step "Removing MCP entry from Claude Desktop config..."
  local claude_desktop_config="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
  if [[ -f "$claude_desktop_config" ]]; then
    CLAUDE_DESKTOP_CONFIG="$claude_desktop_config" python3 -c "
import json, os
path = os.environ['CLAUDE_DESKTOP_CONFIG']
with open(path, 'r') as f:
    config = json.load(f)
if 'mcpServers' in config and 'trace' in config['mcpServers']:
    del config['mcpServers']['trace']
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)
    print('  Removed trace from mcpServers')
else:
    print('  trace not found in mcpServers (skipped)')
" 2>/dev/null || warn "Could not update Claude Desktop config – remove manually"
  else
    echo "  Claude Desktop config not found (skipped)"
  fi

  # Remove TRACE hooks from Claude Code settings
  step "Removing Claude Code hooks..."
  local claude_settings="$HOME/.claude/settings.json"
  if [[ -f "$claude_settings" ]]; then
    CLAUDE_SETTINGS="$claude_settings" python3 -c "
import json, os
path = os.environ['CLAUDE_SETTINGS']
with open(path, 'r') as f:
    settings = json.load(f)
changed = False
for hook_type in list(settings.get('hooks', {}).keys()):
    filtered = [
        h for h in settings['hooks'][hook_type]
        if 'trace' not in str(h).lower() and 'session_logger' not in str(h).lower()
    ]
    if len(filtered) != len(settings['hooks'][hook_type]):
        settings['hooks'][hook_type] = filtered
        changed = True
if changed:
    with open(path, 'w') as f:
        json.dump(settings, f, indent=2)
    print('  Removed TRACE hooks from ~/.claude/settings.json')
else:
    print('  No TRACE hooks found in ~/.claude/settings.json (skipped)')
" 2>/dev/null || warn "Could not update ~/.claude/settings.json – remove hooks manually"
  else
    echo "  ~/.claude/settings.json not found (skipped)"
  fi

  # Remove ~/.trace/ directory
  step "Removing ~/.trace/ directory..."
  if [[ -d "$HOME/.trace" ]]; then
    rm -rf "$HOME/.trace"
    echo "  Removed: ~/.trace/"
  else
    echo "  ~/.trace/ not found (skipped)"
  fi

  echo ""
  ok "TRACE uninstalled. Your repo is still at ${SCRIPT_DIR}"
  echo ""
}

# ── Main menu ─────────────────────────────────────────────────────────────────
show_menu() {
  local default=1
  [[ "$TRACE_INSTALLED" == true ]] && default=2

  echo "  What would you like to do?"
  echo ""

  local -a labels=(
    "1  Install TRACE"
    "2  Add project to TRACE"
    "3  Update TRACE          keeps all your data"
    "4  Remove project"
    "5  Uninstall TRACE       removes everything"
    "6  Exit"
  )

  local i
  for i in "${!labels[@]}"; do
    local num=$(( i + 1 ))
    if [[ "$num" == "$default" ]]; then
      echo -e "  ${GREEN}${BOLD}→ ${labels[$i]}${RESET}"
    else
      echo    "      ${labels[$i]}"
    fi
  done

  echo ""
  local choice
  read -r -p "  ❯ [$default]: " choice || true
  choice="${choice:-$default}"

  case "$choice" in
    1)
      echo ""
      echo -e "  ${BOLD}Sets up TRACE from scratch – hooks, dashboard, tokenizer check${RESET}"
      mode_fresh_install
      ;;
    2)
      echo ""
      echo -e "  ${BOLD}Registers a project directory and installs the Claude Code hook${RESET}"
      mode_add_project ""
      ;;
    3)
      echo ""
      echo -e "  ${BOLD}git pull + pip install + reload LaunchAgents – user data untouched${RESET}"
      mode_update
      ;;
    4)
      echo ""
      echo -e "  ${BOLD}Removes hook from a project and unregisters it from TRACE${RESET}"
      mode_remove_project ""
      ;;
    5)
      echo ""
      echo -e "  ${BOLD}Removes all LaunchAgents, MCP entry, ~/.trace/ – asks for confirmation${RESET}"
      mode_uninstall
      ;;
    6)
      echo "Bye."
      exit 0
      ;;
    *)
      err "Invalid choice: $choice"
      ;;
  esac
}

# ── Entry point ───────────────────────────────────────────────────────────────
SUBCMD="${1:-}"
SUBCMD_PATH="${2:-}"

clear
show_header

case "$SUBCMD" in
  "")         show_menu ;;
  install)    mode_fresh_install ;;
  add)        mode_add_project "$SUBCMD_PATH" ;;
  remove)     mode_remove_project "$SUBCMD_PATH" ;;
  update)     mode_update ;;
  uninstall)  mode_uninstall ;;
  *)
    err "Unknown command: '$SUBCMD'
  Usage: bash trace.sh [install|add|remove|update|uninstall] [path]
  Examples:
    bash trace.sh add ~/projects/myapp
    bash trace.sh remove ~/projects/myapp
    bash trace.sh update"
    ;;
esac
