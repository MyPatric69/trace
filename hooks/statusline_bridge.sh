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
DURATION_MS="$(printf '%s' "$INPUT" | jq -r '.cost.total_duration_ms // 0')"
API_DURATION_MS="$(printf '%s' "$INPUT" | jq -r '.cost.total_api_duration_ms // 0')"
LINES_ADDED="$(printf '%s' "$INPUT" | jq -r '.cost.total_lines_added // 0')"
LINES_REMOVED="$(printf '%s' "$INPUT" | jq -r '.cost.total_lines_removed // 0')"
PROJECT_DIR="$(printf '%s' "$INPUT" | jq -r '.workspace.project_dir // ""')"
RATE_LIMIT_5H="$(printf '%s' "$INPUT" | jq -c '.rate_limits.five_hour.used_percentage // null')"
RATE_LIMIT_7D="$(printf '%s' "$INPUT" | jq -c '.rate_limits.seven_day.used_percentage // null')"
CACHE_HIT_RATIO="$(printf '%s' "$INPUT" | jq -c '.prompt_cache.hit_ratio // null')"
CACHE_WARM="$(printf '%s' "$INPUT" | jq -c '.prompt_cache.warm // null')"
PR_NUMBER="$(printf '%s' "$INPUT" | jq -c '.pr.number // null')"
PR_URL="$(printf '%s' "$INPUT" | jq -c '.pr.url // null')"
PR_REVIEW_STATE="$(printf '%s' "$INPUT" | jq -c '.pr.review_state // null')"

# ── Derived display values ────────────────────────────────────────────────────
# Short model name: claude-sonnet-4-6-20251022 → sonnet-4-6
MODEL_SHORT="$(printf '%s' "$MODEL_ID" | sed 's/^claude-//' | sed 's/-[0-9]\{8\}$//')"

PROJECT="$(basename "$CWD")"
[[ -z "$PROJECT" ]] && PROJECT="unknown"

BRANCH="$(git -C "$CWD" rev-parse --abbrev-ref HEAD 2>/dev/null)"
if [ ${#BRANCH} -gt 20 ]; then BRANCH="${BRANCH:0:20}..."; fi
BRANCH_SEG=""
[ -n "$BRANCH" ] && BRANCH_SEG=" | 🌿 $BRANCH"

COST_FMT="$(printf '$%.2f' "$COST" 2>/dev/null || printf '$0.00')"
CTX_INT="$(printf '%.0f' "$USED_PCT" 2>/dev/null || printf '0')"

# Duration: "XhYm" once an hour is crossed, "XmYs" below that.
_DUR_SEC=$(( ${DURATION_MS:-0} / 1000 ))
_DUR_H=$(( _DUR_SEC / 3600 ))
_DUR_M=$(( (_DUR_SEC % 3600) / 60 ))
_DUR_S=$(( _DUR_SEC % 60 ))
if [ "$_DUR_H" -gt 0 ]; then
    DURATION_FMT="$(printf '%dh %dm' "$_DUR_H" "$_DUR_M")"
else
    DURATION_FMT="$(printf '%dm %ds' "$_DUR_M" "$_DUR_S")"
fi

# ── ANSI colors ───────────────────────────────────────────────────────────────
TEAL='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'

# Adaptive thresholds — mirrors engine/live_tracker.py effective_context_thresholds():
# windows > 200K (Pro/Max 1M) cap the warn/critical percentages at 20/40 so the
# same absolute token budget (~200K/~400K) triggers the color change regardless
# of window size, instead of scaling up with it.
if [ "${CTX_SIZE:-200000}" -gt 200000 ] 2>/dev/null; then
    WARN_PCT=20
    CRIT_PCT=40
else
    WARN_PCT=60
    CRIT_PCT=85
fi

CTX_COLOR="$GREEN"
if   [ "${CTX_INT:-0}" -ge "$CRIT_PCT" ] 2>/dev/null; then CTX_COLOR="$RED"
elif [ "${CTX_INT:-0}" -ge "$WARN_PCT" ] 2>/dev/null; then CTX_COLOR="$YELLOW"
fi

# 10-block progress bar, filled proportionally to CTX_INT (rounded to nearest block).
BAR_FILLED=$(( (${CTX_INT:-0} + 5) / 10 ))
[ "$BAR_FILLED" -lt 0 ] 2>/dev/null && BAR_FILLED=0
[ "$BAR_FILLED" -gt 10 ] 2>/dev/null && BAR_FILLED=10
BAR_EMPTY=$((10 - BAR_FILLED))
CTX_BAR="$(printf '%*s' "$BAR_FILLED" '' | tr ' ' '█')$(printf '%*s' "$BAR_EMPTY" '' | tr ' ' '░')"

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
    --argjson session_duration_ms         "${DURATION_MS:-0}" \
    --argjson api_duration_ms             "${API_DURATION_MS:-0}" \
    --argjson lines_added                 "${LINES_ADDED:-0}" \
    --argjson lines_removed               "${LINES_REMOVED:-0}" \
    --arg     project_dir                 "$PROJECT_DIR" \
    --argjson rate_limit_5h_pct           "${RATE_LIMIT_5H:-null}" \
    --argjson rate_limit_7d_pct           "${RATE_LIMIT_7D:-null}" \
    --argjson cache_hit_ratio             "${CACHE_HIT_RATIO:-null}" \
    --argjson cache_warm                  "${CACHE_WARM:-null}" \
    --argjson pr_number                   "${PR_NUMBER:-null}" \
    --argjson pr_url                      "${PR_URL:-null}" \
    --argjson pr_review_state             "${PR_REVIEW_STATE:-null}" \
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
      model:$model,
      session_duration_ms:$session_duration_ms,
      api_duration_ms:$api_duration_ms,
      lines_added:$lines_added,
      lines_removed:$lines_removed,
      project_dir:$project_dir,
      rate_limit_5h_pct:$rate_limit_5h_pct,
      rate_limit_7d_pct:$rate_limit_7d_pct,
      cache_hit_ratio:$cache_hit_ratio,
      cache_warm:$cache_warm,
      pr_number:$pr_number,
      pr_url:$pr_url,
      pr_review_state:$pr_review_state}' 2>/dev/null || printf '{}'
)"

# ── POST to dashboard (synchronous, max 1 s – connection refused exits fast) ──
TRACE_ACTIVE=false
if curl -s --max-time 1 -o /dev/null \
        -X POST http://localhost:8080/api/statusline \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" 2>/dev/null; then
    TRACE_ACTIVE=true
fi

# ── Output status line (two lines) ────────────────────────────────────────────
if [ "$TRACE_ACTIVE" = true ]; then
    printf "[%s] 📁 %s%s\n${CTX_COLOR}%s %s%%${RESET} | %s | ⏱ %s | ${TEAL}● TRACE${RESET}\n" \
        "$MODEL_SHORT" "$PROJECT" "$BRANCH_SEG" "$CTX_BAR" "$CTX_INT" "$COST_FMT" "$DURATION_FMT"
else
    printf "[%s] 📁 %s%s\n${CTX_COLOR}%s %s%%${RESET} | %s | ⏱ %s\n" \
        "$MODEL_SHORT" "$PROJECT" "$BRANCH_SEG" "$CTX_BAR" "$CTX_INT" "$COST_FMT" "$DURATION_FMT"
fi
