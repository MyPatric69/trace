#!/usr/bin/env bash
# TRACE – one-time global Git template setup.
#
# After running this script, every new git clone or git init will
# automatically include the TRACE post-commit hook.
#
# Usage: bash hooks/setup_global_template.sh

set -euo pipefail

TRACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_DIR="$HOME/.git-template"
HOOKS_DIR="$TEMPLATE_DIR/hooks"

# 1. Create global template hooks directory
mkdir -p "$HOOKS_DIR"

# 2. Write hook with hardcoded TRACE installation path
HOOK_DST="$HOOKS_DIR/post-commit"

cat > "$HOOK_DST" << HOOK
#!/usr/bin/env bash
# TRACE post-commit hook – installed via global git template
# TRACE installation: $TRACE_ROOT

PROJECT_ROOT="\$(git rev-parse --show-toplevel 2>/dev/null)"
TRACE_HOME="$TRACE_ROOT"

# Auto-register project in ~/.trace/trace.db if not yet known
python3 -c "
import sys
sys.path.insert(0, '\$TRACE_HOME')
from engine.auto_register import register_if_unknown
register_if_unknown('\$PROJECT_ROOT')
" 2>/dev/null || true

# Update AI_CONTEXT.md if doc-relevant changes detected
python3 "\$TRACE_HOME/engine/hook_runner.py" "\$PROJECT_ROOT" 2>/dev/null || true
HOOK

chmod +x "$HOOK_DST"

# 3. Configure git to use the template directory
git config --global init.templateDir "$TEMPLATE_DIR"

# 4. Run migration (safe, idempotent)
python3 "$TRACE_ROOT/engine/migrate.py"

echo ""
echo "TRACE global template installed."
echo "Every new git clone/init will include the hook."
echo ""
echo "Template: $TEMPLATE_DIR"
echo "Hook:     $HOOK_DST"
