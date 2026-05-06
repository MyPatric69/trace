# AI_CONTEXT.md – TRACE

> This file is the single re-entry point for AI assistants working on TRACE.
> Keep it current. It replaces reading 5 separate docs on every session start.
> 
> **New sessions:** Also read `WORKING_WITH_CLAUDE.md` for collaboration guidelines.

---

## Project

**Name:** TRACE – Token-aware Realtime AI Context Engine
**Type:** MCP Server (Python / FastMCP)
**License:** MIT
**Repo:** github.com/MyPatric69/trace
**Status:** All phases complete – 600/600 tests green ✓

---

## What TRACE does

TRACE provides two core capabilities for AI development environments (Claude Code, Cursor, Codex):

1. **Token cost tracking** – logs and aggregates API token consumption per project and session
2. **Context intelligence** – keeps `AI_CONTEXT.md` automatically current via git hook integration

Heavy computation runs locally (zero API cost). The MCP layer is an **optional**
convenience surface for Claude Desktop users; the core (hooks, dashboard,
notifications, status line bridge) works without it. Enable MCP via `trace.sh`
Option 9 when needed.

---

## Architecture (current)

```
IDE Layer (Claude Code / Cursor / Codex)
    ↕ MCP protocol                       ↕ PostToolUse / Stop hook
MCP Server Core  [server/main.py]        Live Tracker  [engine/live_tracker.py]
    ↕ internal calls                         ↕ writes
Local Intelligence Engine  [engine/]    ~/.trace/live_session.json
    ↕ read/write
Data Layer  [~/.trace/trace.db · ~/.trace/trace_config.yaml]
    ↕ read
Dashboard  [dashboard/server.py – FastAPI + WebSocket → http://localhost:8080]
```

**Central storage:** All tools use `TraceStore.default()` → `~/.trace/trace.db` and
`~/.trace/trace_config.yaml`. On first run the config is bootstrapped from the project
`trace_config.yaml` to `~/.trace/`.

---

## Project structure

```
trace/
├── AI_CONTEXT.md          ← this file
├── CLAUDE.md
├── VISION.md
├── README.md
├── WORKING_WITH_CLAUDE.md
├── TROUBLESHOOTING.md
├── trace_config.yaml      ← source config (bootstrapped to ~/.trace/ on first run)
├── requirements.txt
│
├── server/
│   ├── main.py            ← FastMCP entry point (6 tools)
│   └── tools/
│       ├── costs.py       ← log_session(), get_costs()
│       ├── context.py     ← update_context(), check_drift()
│       └── session.py     ← new_session(), get_tips()
│
├── engine/
│   ├── store.py           ← SQLite interface – TraceStore.default() → ~/.trace/
│   ├── live_tracker.py    ← PostToolUse hook – incremental transcript parse → live_session.json
│   ├── live_session_hook.py ← Stop hook handler – fires after each completed response
│   ├── transcript_parser.py ← Shared transcript token-counting logic
│   ├── session_logger.py  ← SessionEnd hook – parses full transcript, logs to DB
│   ├── handoff_builder.py ← build_handoff() – enriches compress() output with CLAUDE.md/backlog/git context
│   ├── notifier.py        ← notify() – macOS notification + sound on health escalation
│   ├── git_watcher.py
│   ├── doc_synthesizer.py
│   ├── context_compressor.py
│   ├── hook_runner.py
│   ├── auto_register.py   ← register_if_unknown() – called by post-commit hook
│   ├── migrate.py         ← one-time migration: local trace.db → ~/.trace/trace.db
│   └── providers/         ← pluggable provider adapters
│       ├── __init__.py    ← get_provider() – reads api_integration.provider from config
│       ├── base.py        ← AbstractProvider interface
│       ├── manual.py      ← default: reads from TraceStore (no credentials needed)
│       ├── anthropic.py   ← Anthropic Usage API (ANTHROPIC_ADMIN_API_KEY)
│       ├── openai.py      ← OpenAI Usage API (OPENAI_API_KEY)
│       └── vertexai.py    ← Google Vertex AI / Cloud Billing API
│
├── hooks/
│   ├── post-commit              ← Git Hook template
│   ├── install_hook.sh
│   ├── setup_global_template.sh
│   ├── setup_claude_hook.sh    ← installs PostToolUse + Stop hooks in ~/.claude/settings.json
│   ├── setup_dashboard_autostart.sh ← creates macOS LaunchAgent for dashboard autostart at login
│   └── remove_dashboard_autostart.sh ← unloads and removes the LaunchAgent
│
├── dashboard/
│   ├── server.py          ← FastAPI app + WebSocket + 15+ REST endpoints
│   ├── index.html         ← single-page UI, auto-refresh every 120s
│   ├── favicon.svg
│   └── start.sh           ← bash dashboard/start.sh → http://localhost:8080
│
├── docs/
│   ├── manifest_de.html
│   └── manifest_en.html
│
└── tests/                 ← 592 tests, all green

~/.trace/
├── trace.db               ← single central DB for all projects
├── trace_config.yaml      ← central config (bootstrapped from project on first run)
├── live_session.json      ← current in-progress session (written by live_tracker.py)
├── last_health.json       ← persisted health state across browser refreshes
└── session_logger.log     ← hook error log
```

---

## Current phase: All phases complete

**602/602 tests green ✓ (2026-05-06)**

**Phase 1 (complete – 24 tests):**
- `trace_config.yaml` – project registry, model prices, session thresholds, budgets
- `engine/store.py` – SQLite schema, `TraceStore` with `add_session()` → `int`, `calculate_cost()` → `float`
- `server/tools/costs.py` – `log_session()` + `get_costs()` with period filters

**Phase 2 (complete – 70 tests):**
- `engine/git_watcher.py` – `GitWatcher` class
- `engine/doc_synthesizer.py` – `DocSynthesizer`, delta-based `AI_CONTEXT.md` updates
- `server/tools/context.py` – `check_drift()` + `update_context()` MCP tools
- `engine/hook_runner.py` + `hooks/post-commit` + `hooks/install_hook.sh` – git hook system

**Phase 3 (complete – 47 tests):**
- `engine/context_compressor.py` – `ContextCompressor`, token-optimized re-entry prompt
- `server/tools/session.py` – `new_session()` + `get_tips()` MCP tools

**Phase 4 (complete – 26 tests):**
- `dashboard/server.py` – FastAPI app, reads `~/.trace/trace.db` via `TraceStore`
- `dashboard/index.html` – single-page UI, IBM Plex fonts, flat design
- `engine/store.py` – `get_token_summary()` + `get_sessions_with_projects()` added

**Dashboard feature expansions (complete):**
- **Live session tracking** – `engine/live_tracker.py` (PostToolUse hook), `engine/live_session_hook.py` (Stop hook), `engine/transcript_parser.py` (shared parsing); `/api/live` + `/api/live/clear` endpoints; WebSocket push to connected browsers
- **Turns tracking** – `turns` column in `sessions` table; `upsert_live_session()` + `delete_live_session()` in store; turns displayed in live panel, health bar, daily summary
- **Provider badges** – `resolve_provider(model)` helper + `/api/providers` endpoint; per-project badges with model subtitles; provider detection: `claude-*` → anthropic, `gpt-*/o1-*/o3-*/o4-*` → openai, `gemini-*/gemma-*` → google
- **Hook refinement** – `engine/hook_runner.py` runs synthesis on every commit type (no `SKIP_PREFIXES`/`should_skip()`); staleness fallback forces synthesis when `AI_CONTEXT.md` is >2 days old; `engine/doc_synthesizer.py` adds `get_context_age_days()`; `/api/drift` response includes `ai_context_age_days`; dashboard shows amber badge when >2 days old
- **Multi-session live tracking** – `engine/live_tracker.py` writes per-session files to `~/.trace/live/{session_id}.json`; `get_all_active()` returns all non-stale sessions (5 min, `_STALE_SECONDS=300`); `clear(session_id=None)` removes specific or all session files; backward compat: migrates legacy `live_session.json` on first write; `/api/live` returns `{"active", "sessions": [...], "last_health"}`; dashboard live panel shows single-session detail or multi-session compact list
- **7-day date picker** – `/api/stats/{date}` endpoint + `/api/today` summary
- **Configurable health thresholds** – green/yellow/red read from `trace_config.yaml` (no hardcoded 100k)
- **MCP server panel** – add/remove MCP servers via UI; reads from both Claude config locations
- **Persistence** – project filter in localStorage; health state in `~/.trace/last_health.json`
- **Auto-refresh** – 120s interval (was 30s); WebSocket used for live data push
- **Editable session health thresholds** – `POST /api/settings` accepts `warn_tokens` / `critical_tokens`; validates `warn > 0` and `warn < critical` (400 on failure); writes to `session_health` block in `~/.trace/trace_config.yaml`; `GET /api/status` now returns both threshold values; Settings popover has number inputs, preset buttons (Sparsam 50k/100k · Standard 80k/150k · Intensiv 120k/200k), Save button with inline error/confirmation, and live health bar refresh after save
- **Settings popover** – Settings moved from bottom panel into a compact header popover
- **Health bar iframe fix** – `.health-row` changed to `display:block; min-height:2.5rem` (was flex); `.health-bar-wrap` to `display:block; width:100%` (removed flex:1 and position:relative); `.health-bar` gains explicit `display:block; width:100%`; `.health-fill` uses `height:8px` instead of `height:100%` to avoid percentage-height collapse in VS Code Simple Browser iframe; token label now sits below the bar in block flow; test documented in `tests/FRONTEND_TESTS.md` (Test 11) (gear icon + "Settings" pill button in `.header-right`); popover is 300px wide, right-aligned below button, `z-index 500`; contains notification toggles (auto-save on change), health threshold inputs + presets + Save button (posts all values, shows "Gespeichert" for 2s); closes on outside click; old bottom Settings panel removed

**Dashboard REST endpoints (current):**
```
GET  /api/status               – includes baseline_model
GET  /api/projects
GET  /api/costs                ?period=
GET  /api/costs/{project}      ?period=
GET  /api/tokens               ?project= &period=
GET  /api/stats/{date}         ?project=
GET  /api/today                ?project=
GET  /api/models               ?period= &project=
GET  /api/providers
GET  /api/provider             ?period=
GET  /api/drift/{project}
GET  /api/sync/{project}
GET  /api/live                 ?project=
GET  /api/activity             – activity stats and 52-week heatmap
GET  /api/efficiency           ?project= &period= – cost vs. baseline model
POST /api/live/clear
POST /api/statusline           – real-time update from status line bridge
POST /api/settings             – accepts warn_tokens, critical_tokens, monthly_budget_usd, baseline_model
GET  /api/tips                 ?project_name=
GET  /api/new_session/{project}  ?dry_run=
WS   /ws
```

**Enriched handoff prompt (complete – 30 tests):**
- `engine/handoff_builder.py` – `build_handoff(repo_path, base_prompt)` enriches the compress() output with: `## Current Phase` (from CLAUDE.md), `## Open Task` (first incomplete checkbox from highest-numbered backlog/epic-*.md), `## Files to Read First` (git diff HEAD~3, max 5, filtered to .ts/.tsx/.md/.py/.yaml), `## Known Constraints` (CLAUDE.md Runtime Rules), `## Test Command` (test/type-check line from CLAUDE.md Dev Commands)
- Staleness warning prepended when AI_CONTEXT.md mtime > 2 days
- `server/tools/session.py` – calls `build_handoff` after `compress()`, falls back silently on error
- `tests/test_handoff_builder.py` – 30 tests

**macOS notifications (complete – 20 tests):**
- `engine/notifier.py` – `notify()` → `_send_notification()` + `_play_sound()`; notifications: Darwin via osascript, Windows via win10toast (optional/graceful fallback), Linux via notify-send; sound: Darwin afplay, Windows winsound, Linux paplay; zero required dependencies
- `engine/live_tracker.py` – detects health escalations (green→yellow, green/yellow→red) by comparing `prev_health` stored in the per-session file; fires `notify()` only on escalation; no duplicate notifications on same status
- `trace_config.yaml` – `notifications` block: `enabled`, `sound`, `sound_warn` (Tink), `sound_critical` (Funk)
- `dashboard/server.py` – `POST /api/settings` writes `notifications_enabled`/`notifications_sound` to `~/.trace/trace_config.yaml`; `GET /api/status` includes both fields
- `dashboard/index.html` – Settings panel with Notifications + Sound toggles; Sound greyed out when Notifications off; persisted via `POST /api/settings` on toggle change

**Dashboard consolidation and recent expansions (complete):**
- **Context window utilization** – `peak_context_tokens` column in `sessions` table; `engine/live_tracker.py` records peak during session as `max(input + cache_creation + cache_read per turn)` – full context window load, not just uncached input; `/api/live` response includes `peak_context_tokens`; dashboard health panel shows utilization bar
- **Activity section** – `/api/activity` endpoint returns session counts, turn totals, current/longest streak, avg. cost/session, and 52-week heatmap data; `get_activity_stats()` + `get_heatmap_data()` added to `TraceStore`; heatmap uses relative colour scaling (most expensive day = full-intensity teal, no activity = transparent)
- **Monthly budget in Settings** – `POST /api/settings` accepts `monthly_budget_usd` (float, > 0); `GET /api/status` returns `monthly_budget_usd` alongside `warn_tokens`/`critical_tokens`; Settings popover Monthly Budget field saves immediately to `~/.trace/trace_config.yaml`; default $20.00
- **Provider & Model Usage merged** – previously separate "AI Provider" and "Model Usage" panels consolidated into a single "Provider & Model Usage" section; provider badges and model cost bars rendered together
- **Smart recommendations** – cost tips fire when avg. cost/session exceeds $2.00 or when monthly budget utilization exceeds 100%
- **Dynamic heatmap width** – heatmap starts at the Monday of the first data entry and ends at today; grows organically week-by-week up to a 52-week cap; empty state shows a single transparent placeholder column with "No activity yet" label

**Cost Efficiency section (complete – 8 tests):**
- `trace_config.yaml` – `comparison.baseline_model` field (default: `claude-sonnet-4-6`)
- `GET /api/efficiency` – computes actual vs. baseline cost per period; returns `actual_cost`, `baseline_cost`, `savings`, `actual_model`, `baseline_model`, `period`; accepts `?project=` and `?period=` (default: week)
- `GET /api/status` – now returns `baseline_model` from `comparison` config block
- `POST /api/settings` – accepts optional `baseline_model`; validates against `models` block; saves to `comparison.baseline_model`
- Dashboard "Cost Efficiency" panel (section 6) – two bar rows (actual in red, baseline in teal), savings row in amber/teal; when `actual_model === baseline_model` bars are hidden and only the "already efficient" message + subtitle shown; all cost values rounded to 2 decimal places (`toFixed(2)`); savings recommendation shown if savings > $5/week
- Settings popover – "Baseline model" dropdown populated from `/api/tokenize/models`; sorted alphabetically; saved with all other settings

**Tokenizer ratio check (complete – 7 tests):**
- `engine/tokenizer_check.py` – standalone script; reads current model from live sessions/DB, calls `POST /v1/messages/count_tokens` twice with fixed ~500-token reference text, writes `~/.trace/tokenizer_ratio.json`
- `engine/tokenizer_check_wrapper.sh` – reads `ANTHROPIC_API_KEY` from macOS Keychain; uses hardcoded pyenv Python path with fallback; called by LaunchAgent
- `hooks/setup_tokenizer_check.sh` / `hooks/remove_tokenizer_check.sh` – LaunchAgent management (daily at 07:00, RunAtLoad)
- `GET /api/tokenizer_ratio` – returns file contents or `{"ratio": 1.0, "checked_at": null}` when missing
- Dashboard Cost Efficiency panel – amber row shown when ratio > 1.05: _"Tokenizer: {model} uses {ratio}x more tokens than {baseline}"_

**Config cleanup:**
- `models:` block: GPT models removed (TRACE is Claude-only); 7 Claude models reordered: sonnet-4-6 (default), sonnet-4-7, sonnet-4-5, opus-4-7, opus-4-6, opus-4-5, haiku-4-5

**Status line bridge extended (complete – 8 tests):**
- `hooks/statusline_bridge.sh` – extracts `cost.total_duration_ms`, `cost.total_api_duration_ms`, `cost.total_lines_added`, `cost.total_lines_removed`, `workspace.project_dir` and includes them in the `POST /api/statusline` payload; git branch inserted between project name and CTX% in terminal output (`[model] project | branch | CTX: X% | $cost | ● TRACE`); branch truncated to 20 chars with `...` if longer; silently omitted when not in a git repo
- `dashboard/server.py` – `StatuslineRequest` accepts `session_duration_ms`, `api_duration_ms`, `lines_added`, `lines_removed`, `project_dir`; handler stores them in the live session file (update: only when non-zero to avoid regressing data; create: always); `project_dir` used as fallback for project detection when `cwd`-based lookup returns nothing
- `dashboard/index.html` – `fmtDuration(ms)` helper (ms → `Xm` / `Xh Ym` / `Xh`); single-session live panel shows DURATION row below context bar when duration > 0 (`2h 15m (API: 23m)`) and CHANGES row when lines > 0 (`+142 / -38` in teal/red); `.live-stat-row` CSS class added

**Auto AI_CONTEXT.md refresh on SessionEnd (complete – 2 new tests):**
- `engine/doc_synthesizer.py` – new `DocSynthesizer.update_if_stale()` method encapsulates the drift-check + section-update orchestration that previously lived inline in `hook_runner.run()`. Returns `True` when `AI_CONTEXT.md` was rewritten, `False` when no work was needed; never raises.
- `engine/hook_runner.py` – `run()` now delegates to `synth.update_if_stale()`; behaviour for the post-commit hook is unchanged.
- `engine/session_logger.py` – `run()` calls `DocSynthesizer(cwd).update_if_stale()` after the session has been logged and the live file cleared. Failures are caught and logged; the SessionEnd hook never propagates synthesizer errors.
- `tests/test_session_logger.py` – `test_run_invokes_doc_synthesizer_after_logging` verifies `update_if_stale` is called and the session is still persisted; `test_run_logs_session_even_when_doc_synthesizer_raises` verifies a synthesizer crash is swallowed.

**MCP setup decoupled from install (no new tests – manual verification):**
- `trace.sh` `mode_fresh_install` no longer mentions Claude Desktop / MCP. Success message points users to `Option 9 (Setup MCP server)` for optional handoff tooling.
- `mode_setup_mcp` (Option 9) – idempotently inserts a `trace` entry into `~/Library/Application Support/Claude/claude_desktop_config.json` with `command=python3` and `args=[<repo>/server/main.py]`; prints `✅ MCP server added. Restart Claude Desktop to activate.` or `✅ MCP server already configured.` on second run.
- `mode_remove_mcp` (Option 10) – removes the `trace` entry; prints `✅ MCP server removed. Restart Claude Desktop.` or `⚠️ MCP server not found in config.` when absent.
- New subcommands: `bash trace.sh setup-mcp` / `bash trace.sh remove-mcp`.
- README "MCP server (optional)" section documents when to enable, when to skip, and the setup/remove commands. Old Step 4 in Installation now points at this section instead of inlining the JSON edit.

**Status line bridge (original – 4 tests):**
Provides real-time context window updates sourced directly from the Claude Code status line API — not estimated from transcript parsing. Fills the gap during long tool calls where the Stop hook does not fire until the full turn completes. Terminal output: `[model] project | CTX: X% | $cost | ● TRACE`. CTX% is the percentage of Claude Code's 200k context window used; value is official, not estimated.
- `hooks/statusline_bridge.sh` – reads Claude Code session JSON from stdin, extracts session_id/cwd/context_window/cost/model with jq, POSTs to `POST /api/statusline` (sync, max-time 1s), outputs `[model] project | CTX: X% | $cost | ● TRACE` (ANSI-colored); `● TRACE` omitted when dashboard unreachable
- `hooks/setup_statusline_bridge.sh` – copies bridge to `~/.claude/statusline_bridge.sh`, adds `statusLine: {type: command, command: ...}` to `~/.claude/settings.json` (merges, idempotent)
- `hooks/remove_statusline_bridge.sh` – removes `statusLine` key from settings.json, deletes `~/.claude/statusline_bridge.sh`
- `dashboard/server.py` – `POST /api/statusline`: updates `context_window_pct`, `peak_context_tokens`, `cost_usd`, `updated_at` on an existing live session file; creates a minimal session file if none exists; detects project from cwd (same logic as LiveTracker); returns 200 always
- `trace.sh` – Option 7 (Setup status line bridge) and Option 8 (Remove status line bridge) added to menu
- `README.md` – "## Status line bridge" section added

**Two-file config split (complete – 14 tests):**
- `engine/config.py` – new `TraceConfig` class; reads system config from `{repo_root}/trace_config.yaml` (models, prices; read-only at runtime) and user config from `~/.trace/user_config.yaml` (thresholds, notifications, budget, comparison, mcp_servers); merges both into a single dict; migrates from legacy `~/.trace/trace_config.yaml` on first run
- `engine/store.py` – `TraceStore.default()` now uses `TraceConfig.default().merged` as `self.config`; `~/.trace/trace_config.yaml` bootstrapped for backward compat (DocSynthesizer / ContextCompressor)
- `dashboard/server.py` – `_load_central_config()` returns `(user_config_path, merged_dict)` where merged includes system models for validation; `_save_and_sync_config()` writes only user keys to `~/.trace/user_config.yaml`, no longer syncs to repo `trace_config.yaml`
- `tests/test_config.py` – 14 tests covering merge, migration, model price lookup, and save operations
- `tests/test_mcp_panel.py`, `tests/test_notifier.py` – fixtures updated to use `user_config.yaml`

**Out of scope:**
- Multi-MCP proxy

---

## Tech stack

| Layer | Technology |
|---|---|
| MCP Server | Python 3.11+ / FastMCP |
| Dashboard | FastAPI + WebSocket |
| Storage | SQLite (via `sqlite3` stdlib) |
| Config | YAML (`pyyaml`) |
| Git integration | `gitpython` (Phase 2) |
| Package mgmt | `pyenv` + `pip` |

---

## Key decisions

- **Local-heavy, API-light** – all heavy work in engine/, MCP returns summaries only
- **SQLite over flat files** – queryable, no extra dependencies, single file per workspace
- **FastMCP over raw MCP** – reduces boilerplate, Pythonic, well-maintained
- **Delta-based doc updates** – never full rewrites, only targeted patches (Phase 2)
- **`add_session()` returns `session_id` only** – cost retrieved separately via `store.calculate_cost()`
- **Prefix matching for model prices** – handles date-suffixed model strings (e.g. `claude-sonnet-4-5-20251022`)
- **Incremental transcript parsing** – `live_tracker.py` tracks byte offset, only parses new lines per call
- **`upsert_live_session()` not `add_session()`** – live sessions update in place; `delete_live_session()` called at SessionEnd before `add_session()` finalises

---

## Next steps

No open items – all phases and feature expansions complete. Tests green.

---

**Stale session persistence (complete – 18 new tests):**
- `engine/live_tracker.py` – `get_all_active()` now includes stale sessions with `"stale": True` (previously filtered out); `get_live()` still filters stale for callers that want only fresh sessions
- `dashboard/server.py` – `api_today()` filters stale sessions from live totals to avoid double-counting
- `dashboard/index.html` – Live Session panel shows "paused X min ago" label next to project name for stale sessions; multi-session view summarises "N active, M paused sessions"; `pausedLabel()` helper computes minutes/hours since `updated_at`; `.live-paused` CSS class added

---

## Last updated

2026-05-06 – AI_CONTEXT.md auto-refresh wired into SessionEnd hook via new `DocSynthesizer.update_if_stale()`; `hook_runner.run()` now delegates to the same method (DRY). 602/602 tests green.
