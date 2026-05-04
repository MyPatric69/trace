#!/usr/bin/env bash
# TRACE Status Line Bridge
#
# Claude Code pipes a JSON session object to this script's stdin after every
# assistant message.  The script:
#   1. Extracts token/cost/model data with jq
#   2. POSTs to the local TRACE dashboard (fire-and-forget, 1 s timeout)
#   3. Prints a formatted status line to stdout
#
# Requirements: jq  (brew install jq)
# Install:  bash hooks/setup_statusline_bridge.sh
# Remove:   bash hooks/remove_statusline_bridge.sh

# Never exit on error – a failing status line script would break Claude Code
set +e

INPUT="$(cat)"

# ── jq check ─────────────────────────────────────────────────────────────────
if ! command -v jq &>/dev/null; then
    printf "[trace] jq required – brew install jq\n"
    exit 0
fi

# ── Extract fields ────────────────────────────────────────────────────────────
SESSION_ID="$(printf '%s' "$INPUT" | jq -r '.session_id // ""')"
CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // ""')"
USED_PCT="$(printf '%s' "$INPUT" | jq -r '.context_window.used_percentage // 0')"
CTX_SIZE="$(printf '%s' "$INPUT" | jq -r '.context_window.context_window_size // 200000')"
INPUT_TOK="$(printf '%s' "$INPUT" | jq -r '.context_window.current_usage.input_tokens // 0')"
CACHE_CC="$(printf '%s' "$INPUT" | jq -r '.context_window.current_usage.cache_creation_input_tokens // 0')"
CACHE_CR="$(printf '%s' "$INPUT" | jq -r '.context_window.current_usage.cache_read_input_tokens // 0')"
OUTPUT_TOK="$(printf '%s' "$INPUT" | jq -r '.context_window.current_usage.output_tokens // 0')"
TOTAL_IN="$(printf '%s' "$INPUT" | jq -r '.context_window.total_input_tokens // 0')"
TOTAL_OUT="$(printf '%s' "$INPUT" | jq -r '.context_window.total_output_tokens // 0')"
COST="$(printf '%s' "$INPUT" | jq -r '.cost.total_cost_usd // 0')"
MODEL_ID="$(printf '%s' "$INPUT" | jq -r '.model.id // "unknown"')"

# ── Derived display values ────────────────────────────────────────────────────
# Short model name: claude-sonnet-4-6-20251022 → sonnet-4-6
MODEL_SHORT="$(printf '%s' "$MODEL_ID" | sed 's/^claude-//' | sed 's/-[0-9]\{8\}$//')"

PROJECT="$(basename "$CWD")"
[[ -z "$PROJECT" ]] && PROJECT="unknown"

COST_FMT="$(printf '$%.2f' "$COST" 2>/dev/null || printf '$0.00')"
CTX_INT="$(printf '%.0f' "$USED_PCT" 2>/dev/null || printf '0')"

# ── ANSI colors ───────────────────────────────────────────────────────────────
TEAL='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'

CTX_COLOR="$GREEN"
if   [ "${CTX_INT:-0}" -ge 85 ] 2>/dev/null; then CTX_COLOR="$RED"
elif [ "${CTX_INT:-0}" -ge 60 ] 2>/dev/null; then CTX_COLOR="$YELLOW"
fi

# ── Build JSON payload ────────────────────────────────────────────────────────
PAYLOAD="$(jq -cn \
    --arg     session_id                  "$SESSION_ID" \
    --arg     cwd                         "$CWD" \
    --argjson context_window_pct          "${USED_PCT:-0}" \
    --argjson context_window_size         "${CTX_SIZE:-200000}" \
    --argjson input_tokens                "${INPUT_TOK:-0}" \
    --argjson cache_creation_input_tokens "${CACHE_CC:-0}" \
    --argjson cache_read_input_tokens     "${CACHE_CR:-0}" \
    --argjson output_tokens               "${OUTPUT_TOK:-0}" \
    --argjson total_input_tokens          "${TOTAL_IN:-0}" \
    --argjson total_output_tokens         "${TOTAL_OUT:-0}" \
    --argjson cost_usd                    "${COST:-0}" \
    --arg     model                       "$MODEL_ID" \
    '{session_id:$session_id,cwd:$cwd,
      context_window_pct:$context_window_pct,
      context_window_size:$context_window_size,
      input_tokens:$input_tokens,
      cache_creation_input_tokens:$cache_creation_input_tokens,
      cache_read_input_tokens:$cache_read_input_tokens,
      output_tokens:$output_tokens,
      total_input_tokens:$total_input_tokens,
      total_output_tokens:$total_output_tokens,
      cost_usd:$cost_usd,
      model:$model}' 2>/dev/null || printf '{}'
)"

# ── POST to dashboard (synchronous, max 1 s – connection refused exits fast) ──
TRACE_ACTIVE=false
if curl -s --max-time 1 -o /dev/null \
        -X POST http://localhost:8080/api/statusline \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" 2>/dev/null; then
    TRACE_ACTIVE=true
fi

# ── Output status line ────────────────────────────────────────────────────────
if [ "$TRACE_ACTIVE" = true ]; then
    printf "[%s] %s | CTX: ${CTX_COLOR}%s%%${RESET} | %s | ${TEAL}● TRACE${RESET}\n" \
        "$MODEL_SHORT" "$PROJECT" "$CTX_INT" "$COST_FMT"
else
    printf "[%s] %s | CTX: ${CTX_COLOR}%s%%${RESET} | %s\n" \
        "$MODEL_SHORT" "$PROJECT" "$CTX_INT" "$COST_FMT"
fi
