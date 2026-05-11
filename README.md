# TRACE

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue) ![MIT License](https://img.shields.io/badge/license-MIT-green) ![MCP Server](https://img.shields.io/badge/MCP-server-lightgrey)

TRACE is a local MCP server that tracks token costs and keeps `AI_CONTEXT.md` automatically up to date across all your projects.

[→ Why TRACE exists (Technical Manifest)](docs/manifest_en.html)

---

## Quick install / trace.sh

Clone the repo and run `trace.sh` from the TRACE repo root:

```bash
# Interactive menu
bash trace.sh

# Direct operations
bash trace.sh add ~/projects/myapp
bash trace.sh remove ~/projects/myapp
bash trace.sh update
bash trace.sh uninstall
```

`trace.sh` is always run from the TRACE repo. For project operations you either
pass the path as an argument or are prompted to enter it interactively.

### Auto-detected default

| Situation | Auto-selected menu option |
|---|---|
| `~/.trace/user_config.yaml` does not exist | **1 – Install TRACE** |
| TRACE installed | **3 – Update TRACE** |

### Menu options

| # | Option | What it does |
|---|---|---|
| 1 | Install TRACE | Sets up TRACE from scratch – hooks, dashboard, tokenizer check (MCP not included) |
| 2 | Add project | Prompts for a project path, then registers it and installs the git hook |
| 3 | Update TRACE | `git pull` + `pip install` + reload LaunchAgents – user data untouched |
| 4 | Remove project | Prompts for a project path, then removes its hook and unregisters it |
| 5 | Uninstall TRACE | Removes all LaunchAgents, MCP entry, `~/.trace/` – asks for confirmation |
| 6 | Exit | — |
| 7 | Setup status line bridge | Real-time context/cost in your terminal |
| 8 | Remove status line bridge | Removes the status line bridge |
| 9 | Setup MCP server | Adds TRACE MCP server to Claude Desktop config (optional) |
| 10 | Remove MCP server | Removes TRACE MCP server from Claude Desktop config |

**Project validation** – paths must contain `CLAUDE.md` or `.git`.
Tab completion is available when entering a path interactively.

**One-time prerequisite** – store your API key in Keychain once:

```bash
security add-generic-password -s ANTHROPIC_API_KEY -a anthropic -w sk-ant-...
```

`trace.sh` checks for this key and prints instructions if it is missing.

See [Installation](#installation) below for manual setup and advanced options.

---

## What TRACE does

**Token cost tracking.** Every AI session is logged with model, input tokens, output tokens, and calculated cost. TRACE aggregates this per project and period, surfaces budget alerts when monthly spend approaches the configured limit, and returns actionable optimisation tips when sessions run expensive.

**Context intelligence.** Two hooks keep `AI_CONTEXT.md` automatically current:
the post-commit hook fires after every git commit, and the SessionEnd hook fires
after every Claude Code session. Both delegate to
`DocSynthesizer.update_if_stale()`, which only rewrites the file when
doc-relevant files have changed since the last sync — or as a fallback when
`AI_CONTEXT.md` is older than 2 days. TRACE also detects drift on demand,
generates compressed handoff prompts so new sessions start fully oriented, and
recommends session resets before token costs accelerate.

---

## Why TRACE

Claude Code has built-in commands for session visibility:
`/cost` shows current session spend (API users only),
`/context` shows context window usage. TRACE goes further:

| Feature | `/cost` | `/context` | TRACE |
|---|---|---|---|
| Current session cost | ✅ API only | ❌ | ✅ |
| Token usage (current) | ✅ | ✅ | ✅ |
| Context window visual | ❌ | ✅ | ✅ |
| Cache tokens (separate) | ✅ | ❌ | ✅ |
| Historical sessions | ❌ | ❌ | ✅ |
| Cost per project | ❌ | ❌ | ✅ |
| Monthly budget & alerts | ❌ | ❌ | ✅ |
| Session health indicator | ❌ | ❌ | ✅ |
| macOS notifications | ❌ | ❌ | ✅ |
| Handoff prompt | ❌ | ❌ | ✅ |
| AI_CONTEXT.md auto-update | ❌ | ❌ | ✅ |
| Multi-session tracking | ❌ | ❌ | ✅ |
| Web dashboard | ❌ | ❌ | ✅ |

> **Note:** `/cost` is only visible for API users.
> Claude.ai subscription users (Pro/Max/Team) do not see
> `/cost` by default. TRACE works for all users regardless
> of plan.

---

## Architecture

```
IDE Layer (Claude Code / Cursor / Codex)
    ↕ MCP protocol
MCP Server Core  [server/main.py – FastMCP]
    ↕ internal calls (zero API cost)
Local Intelligence Engine  [engine/]
    ↕ read/write
Data Layer  [~/.trace/trace.db · AI_CONTEXT.md]
```

Core principle: local-heavy, API-light. All heavy computation runs locally. The MCP layer returns summaries only.

---

## Requirements

- Python 3.11+
- git
- Claude Code, Cursor, or any MCP-compatible client

---

## Installation

> **MCP server is optional.** Core TRACE features – hooks, dashboard,
> notifications, status line bridge – work entirely without the MCP server.
> The MCP layer only adds intelligent session handoff (`new_session()`,
> `check_drift()`, `get_costs()`, ...) for users running Claude Desktop.
> See [MCP server (optional)](#mcp-server-optional) below for setup.

**Step 1 – Clone the repo:**

```bash
git clone https://github.com/MyPatric69/trace
cd trace
```

**Step 2 – Install dependencies:**

```bash
pip install -r requirements.txt
```

**Step 3 – Run global template setup (once):**

```bash
bash hooks/setup_global_template.sh
```

This installs the TRACE post-commit hook into `~/.git-template/hooks/` so every future `git clone` or `git init` automatically includes it. Existing repos need one manual install:

```bash
bash hooks/install_hook.sh /path/to/your/project
```

**Step 3.5 – Initialize TRACE (required on fresh install):**

```python
python3 -c "
from engine.store import TraceStore
store = TraceStore.default()
store.init_db()
print('TRACE initialized at:', store.db_path)
"
```

This creates `~/.trace/trace.db` and `~/.trace/user_config.yaml` on first run.
If a `~/.trace/trace_config.yaml` already exists, user settings are migrated
from it automatically.

**Step 3.6 – Install Claude Code hooks (required for live tracking):**

```bash
bash hooks/setup_claude_hook.sh
```

This installs two hooks into `~/.claude/settings.json`:

- **Stop hook** – updates live token counts after every turn
- **SessionEnd hook** – logs the final session cost to the database

Without this step, the live session panel and session cost tracking will not work.

> **Note:** If `~/.claude/settings.json` does not exist yet, the script creates it automatically. If it already exists, the hooks are added without overwriting existing settings.

**Step 4 – (Optional) Enable the MCP server:**

Skip this step if you don't use Claude Desktop or don't need the
session-handoff MCP tools. See [MCP server (optional)](#mcp-server-optional)
below for the one-liner setup.

**Step 5 – Register your first project:**

```python
python3 -c "
from engine.store import TraceStore
store = TraceStore.default()
store.init_db()
store.add_project('my-project', '/path/to/project', 'Description')
"
```

> **Note:** If you get `UNIQUE constraint failed: projects.name`, the project is already registered – safe to ignore. Check with:
> ```python
> python3 -c "from engine.store import TraceStore; print([p['name'] for p in TraceStore.default().list_projects()])"
> ```

---

## MCP server (optional)

The MCP server is a convenience layer on top of TRACE, **not a requirement**.
Everything else – the post-commit hook, dashboard, macOS notifications,
session health, and the status line bridge – works without it.

**What the MCP server adds:**

| Tool | Purpose |
|---|---|
| `new_session` | Compressed handoff prompt for session reset |
| `check_drift` | Reports `AI_CONTEXT.md` staleness vs. recent commits |
| `update_context` | Syncs `AI_CONTEXT.md` from git history |
| `get_costs` | Cost summary per project and period |
| `log_session` | Manual session logging |
| `get_tips` | Cost optimisation recommendations |

**When to enable it:**
- You use Claude Desktop and want one-shot access to TRACE tools from any chat.
- You want `new_session()` available as an MCP tool (otherwise call the API
  endpoint or open the dashboard handoff link).

**When to skip it:**
- You only use Claude Code in the terminal – the hooks already give you live
  session tracking, cost logging, and health. Add TRACE per project via
  `.claude/settings.json` or `claude --mcp-config` if you want the tools there.
- You don't run Claude Desktop at all.

**Setup** (`trace.sh` → Option 9):

```bash
bash trace.sh           # → option 9: Setup MCP server
# or directly:
bash trace.sh setup-mcp
```

This adds a `trace` entry to
`~/Library/Application Support/Claude/claude_desktop_config.json`
pointing at `server/main.py` from the cloned repo. The action is idempotent –
running it twice prints `MCP server already configured.`

Restart Claude Desktop after setup.

**Remove** (`trace.sh` → Option 10):

```bash
bash trace.sh           # → option 10: Remove MCP server
# or directly:
bash trace.sh remove-mcp
```

---

## Configuration

TRACE uses a two-file configuration layout that separates model prices from
personal preferences:

| File | Location | Purpose | Written at runtime? |
|---|---|---|---|
| `trace_config.yaml` | Repo root | Model prices, context windows — updated via `git pull` | **Never** |
| `user_config.yaml` | `~/.trace/` | Thresholds, notifications, budget, baseline model, MCP servers | Yes (Settings UI / API) |

**Update model prices** — just `git pull`. Your settings in `~/.trace/user_config.yaml`
are never touched.

**Reset user settings** — delete `~/.trace/user_config.yaml`. TRACE recreates it from
defaults on the next run.

**Migration** — if you have an existing `~/.trace/trace_config.yaml` from before this
split, TRACE automatically extracts your user settings into `~/.trace/user_config.yaml`
on first run. The old file is left in place untouched.

### ~/.trace/user_config.yaml keys

```yaml
session_health:
  # Quality signal – drives notifications + Request new_session() handoff button.
  warn_context_pct: 60
  critical_context_pct: 85
  # Cost signal – drives only the Session Cost bar in the dashboard.
  warn_tokens: 120000
  critical_tokens: 200000
notifications:
  enabled: true
  sound: true
budgets:
  default_monthly_usd: 125.0
  alert_threshold_pct: 80
comparison:
  baseline_model: claude-sonnet-4-6
mcp_servers: []
```

All values above are the defaults used when no user config exists.
Edit this file directly or use the dashboard ⚙ Settings popover.

---

## Provider configuration

TRACE supports multiple AI providers. Configure yours
in `trace_config.yaml`:

### Supported providers

| Provider  | Usage API | Budget tracking | Credentials       |
|-----------|-----------|-----------------|-------------------|
| manual    | local DB  | manual only     | none (default)    |
| anthropic | ✅        | ✅              | ANTHROPIC_ADMIN_API_KEY (Team/Enterprise only) |
| openai    | ✅        | ✅              | OPENAI_API_KEY    |
| vertexai  | ✅        | optional*       | GCP credentials   |

\*Vertex AI budget tracking depends on quota configuration.

### Configuration

Edit `trace_config.yaml`:

```yaml
api_integration:
  provider: "anthropic"    # manual | anthropic | openai | vertexai
  sync_usage: true
  budget_source: "api"     # api | manual
  monthly_budget_usd: 20.0
```

TRACE reads `api_integration` from the repo's `trace_config.yaml` directly —
no manual copy step needed.

### Anthropic

The Anthropic Usage API requires an **Admin API key**, not a standard API key.

> **Note:** Admin API keys are only available for Team and Enterprise accounts.
> Individual accounts (Pro/Max) cannot create Admin keys and will always fall
> back to local data. This is expected behaviour.
>
> If you have a Team/Enterprise account, Admin keys can be created at:
> https://console.anthropic.com/settings/admin-keys

```bash
export ANTHROPIC_ADMIN_API_KEY=sk-ant-admin...
```

If you only have a standard API key (`ANTHROPIC_API_KEY`), TRACE falls back
to local data automatically – this is the expected behaviour for most
individual developers.

### OpenAI

```bash
export OPENAI_API_KEY=your-key-here
```

### Vertex AI

```bash
gcloud auth application-default login
```

Or:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
```

Budget tracking shown only if quotas are configured in your
Google Cloud project.

### Manual (default)

No credentials needed. Budget set via the ⚙ Settings popover in the
dashboard, or by editing `budgets.default_monthly_usd` in
`~/.trace/user_config.yaml`.

### Adding a new provider

1. Create `engine/providers/yourprovider.py`
2. Implement `AbstractProvider` (see `engine/providers/base.py`)
3. Register in `engine/providers/__init__.py`
4. Open a PR at https://github.com/MyPatric69/trace

### Token count accuracy

A small difference (1–5%) between TRACE and your provider
dashboard is normal and expected.
See the [Token count accuracy](#token-count-accuracy) section for details.

---

## MCP tools

| Tool | Parameters | Description |
|---|---|---|
| `log_session` | `project`, `model`, `input_tokens`, `output_tokens`, `notes` | Log token usage and auto-calculate cost |
| `get_costs` | `project` (opt), `period` (today/week/month/all) | Cost summary per project and period |
| `check_drift` | `project` | Check if `AI_CONTEXT.md` is stale relative to recent commits |
| `update_context` | `project`, `dry_run=False` | Sync `AI_CONTEXT.md` from git history |
| `new_session` | `project`, `dry_run=False` | Generate compressed handoff prompt for session reset |
| `get_tips` | `project` (opt) | Cost optimisation recommendations based on recent sessions |

---

## Web dashboard (optional)

Shows live token usage, costs, drift status, and recommendations for all projects.

**Dashboard sections (top to bottom):**

| # | Section | What it shows |
|---|---|---|
| 1 | Metrics cards | Input / cache / output tokens, session cost, monthly budget % |
| 2 | Live Session | Real-time token counts and cost; shows "paused X min ago" when inactive for >5 min; context window utilization bar showing peak context load vs. model window size |
| 3 | Session Health | Health bar + threshold markers; handoff link |
| 4 | Context Drift + Recommendations | Drift status per project; smart cost tips |
| 5 | Activity | Sessions, streaks, avg. cost/session, 52-week heatmap |
| 6 | Provider & Model Usage | Provider badges per project + model cost bars (last 7 days) |
| 7 | MCP Servers | Registered MCP servers and token-overhead estimate |
| 8 | Token Calculator | Estimate cost before sending a prompt |

**Live Session panel explained:**
- **Context window utilization bar** – shows the highest single-turn context load as a percentage of the model's context window. Calculated as `max(input_tokens + cache_creation_input_tokens + cache_read_input_tokens)` across all turns — this reflects the actual tokens loaded into the model for that API call, including cached context. A session that is 80% cached will still show a realistic utilization here.
  - *Without status line bridge:* updates only when the Stop hook fires (once per completed turn).
  - *With status line bridge:* updates after every assistant message, including during long tool calls. Values sourced directly from Claude Code — not estimated.
- **"Paused X min ago"** – a session is marked stale after 5 minutes of inactivity. The live data is preserved so the panel doesn't disappear mid-session; the label clarifies that no new turns are being tracked.
- **Context Window bar vs. Session Health bar** – Session Health turns yellow/red based on cumulative token spend across all turns (used for handoff recommendations); Context Window shows the peak single-turn load (used to gauge how full the model's context was at peak usage).

**Activity metrics explained:**
- **Sessions** – number of Claude Code sessions started
- **Turns** – individual prompts within a session
- **Streak** – consecutive days with at least one session
- **Avg. Cost/Session** – total cost divided by session count
- The 52-week heatmap uses relative colour scaling: the most expensive day is full-intensity teal; days with no activity are transparent

### Option A – manual start (default)

```bash
bash dashboard/start.sh
# → http://localhost:8080
```

### Option B – autostart at login (macOS)

```bash
bash hooks/setup_dashboard_autostart.sh
# Logs: ~/.trace/dashboard.log
# To disable: bash hooks/remove_dashboard_autostart.sh
```

> **Important:** Run this script once before rebooting.
> The LaunchAgent is registered on first run and starts
> automatically on every subsequent login.
> If not running after reboot, run the script once:
> ```bash
> bash hooks/setup_dashboard_autostart.sh
> ```
> Verify: `launchctl list | grep trace`

### Settings

Click the ⚙ Settings button in the dashboard header to configure:

**Notifications**
- Enable/disable macOS notifications when health thresholds are crossed
- Enable/disable sound (Tink at warning, Funk at critical)

**Context window thresholds** (quality signal)

These percentages drive the **Context Window** bar in the Live Session panel,
the macOS notifications, and the **Request new_session() handoff →** button.
The percentage is taken from the Claude Code status line — it is the official
context window load, not an estimate.

| Field | Default | Effect |
|---|---|---|
| Warn at context window | 60 % | Bar turns amber; warning notification fires once |
| Critical at context window | 85 % | Bar turns red; reset notification fires once; handoff button appears |

**Session cost thresholds** (cost signal)

These token amounts drive the **Session Cost** bar only — they no longer
fire notifications and no longer gate the handoff button. Three presets
or custom values:

| Preset | Cost warning at | Cost critical at | For |
|---|---|---|---|
| Economy | 50,000 tokens | 100,000 tokens | Cost-conscious workflows |
| Standard | 80,000 tokens | 150,000 tokens | Default – recommended |
| Intensive | 120,000 tokens | 200,000 tokens | Large projects / long sessions |

**Monthly Budget**

Set your monthly spending target in USD. The Monthly Budget card in the metrics row shows current month spend as a percentage of this target. Turns amber at 80%, red at 100%.

Default: $20.00. Saved immediately to `~/.trace/user_config.yaml`.

All settings are saved immediately to `~/.trace/user_config.yaml` and
are never overwritten by `git pull`.

> **Note:** The Session Cost bar is only visible when a specific
> project is selected. Select your project from the dropdown in the
> header to see the cost indicator for that project's active session.
> The Context Window bar is always shown for any active session.

### Session health & cost thresholds

TRACE separates two signals:

- **Context window %** – the *quality* signal. Drives notifications and the
  Request new_session() handoff button. Defaults: warn 60 %, critical 85 %.
- **Session cost tokens** – a pure *cost* visualisation. Drives only the
  Session Cost bar in the dashboard.

Configure via the ⚙ Settings popover or directly in
`~/.trace/user_config.yaml`:

```yaml
session_health:
  warn_context_pct: 60     # amber – warning notification fires
  critical_context_pct: 85 # red   – reset notification + handoff button
  warn_tokens: 80000       # Session Cost bar turns amber
  critical_tokens: 150000  # Session Cost bar turns red
```

### Token Calculator – API keys for exact counts

The Token Calculator shows exact token counts when the relevant API key is available:

| Model family | Required key | Without key |
|---|---|---|
| Claude models | `ANTHROPIC_API_KEY` | ~estimate |
| GPT models | `OPENAI_API_KEY` | ~estimate |
| Other models | n/a | ~estimate |

The `ANTHROPIC_API_KEY` is already required for Claude Code and is available automatically if you use TRACE with Claude Code. No extra setup needed for Claude models.

For GPT models, set `OPENAI_API_KEY` in your environment:

```bash
export OPENAI_API_KEY=your-key-here
```

Or store securely in macOS Keychain:

```bash
security add-generic-password -a "$USER" \
  -s "OPENAI_API_KEY" -w "your-key-here"

# Add to ~/.zshrc:
export OPENAI_API_KEY=$(security find-generic-password \
  -a "$USER" -s "OPENAI_API_KEY" -w 2>/dev/null)
```

The dashboard shows an amber badge with a hint when running in estimate mode.

---

## VS Code integration

Open the TRACE dashboard directly inside VS Code:

1. Run the dashboard: `bash dashboard/start.sh`
2. Open Simple Browser: `Cmd+Shift+P` → "Simple Browser: Show"
   → enter `http://localhost:8080`

Or run via Task: `Cmd+Shift+P` → "Tasks: Run Task"
→ "TRACE Dashboard"

The dashboard opens as a VS Code panel alongside your code.
No external browser needed.

---

## Session management best practices

### Why /resume can be expensive

Claude Code's `/resume` command restores a previous session
with its full conversation history. This sounds convenient,
but has a significant hidden cost:

- Every `/resume` replays all prior turns as input tokens –
  including invisible "thinking block signatures" from
  extended thinking turns
- A single resume of a long session can cost 100k+ input
  tokens before you type anything
  ([source: Anthropic GitHub Issue #42260](https://github.com/anthropics/claude-code/issues/42260))
- Anthropic's own documentation recommends against relying
  on session resume for long sessions
  ([source: Anthropic Docs – Work with sessions](https://platform.claude.com/docs/en/agent-sdk/sessions))

### When /resume makes sense

| Situation | Recommendation |
|---|---|
| Short break < 1h, < 20 turns | /resume is fine |
| Long pause or overnight | Use TRACE new_session() |
| New task or topic | New thread, no resume |
| After /clear | Start fresh with new_session() |

### The TRACE alternative

TRACE's `new_session()` generates a compressed handoff
prompt from AI_CONTEXT.md, CLAUDE.md, and recent git
history. The new thread starts with full project context
at a fraction of the token cost.

```bash
# In Claude Code – generate handoff prompt
new_session project="my-project"
```

---

## Expected behaviour

> **Note:** TRACE automatically refreshes `AI_CONTEXT.md` in two situations,
> both expected behaviour – not a bug:
>
> 1. **After every git commit** – via the post-commit hook.
> 2. **After every Claude Code session** – via the SessionEnd hook
>    (`engine/session_logger.py` calls `DocSynthesizer.update_if_stale()`
>    once the session has been logged).
>
> Both paths share the same logic: `AI_CONTEXT.md` is rewritten only when
> doc-relevant files changed since the last sync, with a fallback that forces
> an update when the file is older than 2 days. No manual trigger is needed.
>
> Stage and commit the resulting change as part of your normal workflow:
>
> ```bash
> git add AI_CONTEXT.md
> git commit -m "chore: AI_CONTEXT.md auto-sync"
> ```

---

## CI/CD pipeline support (optional)

For teams using CI/CD pipelines, the hook can be installed automatically as part of the pipeline setup. For developers who prefer manual control or do not use pipelines, the manual install via `install_hook.sh` is fully supported and independent.

---

## Tokenizer ratio check

Two models can have identical published prices per 1k tokens yet one may
produce 10–15% more tokens for the same input – making it measurably more
expensive in practice. The tokenizer ratio check quantifies this difference
daily so the Cost Efficiency panel reflects real-world token counts, not
just nominal rate cards.

> **Note:** TRACE tracks Claude Code sessions only. GPT models have been
> removed from the config – the tokenizer check is Claude-only.

**How it works:**
1. Reads the active model (from live sessions or recent DB) and the
   configured `comparison.baseline_model` from `~/.trace/user_config.yaml`
2. Calls `POST /v1/messages/count_tokens` twice with a fixed ~500-token
   reference text (never changes, so ratios are comparable over time)
3. Writes `ratio = current_tokens / baseline_tokens` to
   `~/.trace/tokenizer_ratio.json`

If ratio > 1.05, the dashboard shows an amber notice in the Cost Efficiency
section: _"Tokenizer: {model} uses {ratio}x more tokens than {baseline} for
the same text – effective cost is higher than the rate card suggests"_.

The baseline model dropdown in Settings is sorted alphabetically.

**Example output** (`~/.trace/tokenizer_ratio.json`) when active model is
`claude-sonnet-4-6` and baseline is `claude-opus-4-7`:

```json
{
  "current_model": "claude-sonnet-4-6",
  "baseline_model": "claude-opus-4-7",
  "current_tokens": 390,
  "baseline_tokens": 500,
  "ratio": 0.78,
  "checked_at": "2026-04-27T07:00:00+00:00",
  "reference_text_hash": "a3f2..."
}
```

A ratio of 0.78 means sonnet-4-6 uses 22% fewer tokens than opus-4-7 for
the same text – no amber warning is shown (ratio ≤ 1.05).

**Setup (macOS LaunchAgent – runs once daily at 07:00):**

```bash
bash hooks/setup_tokenizer_check.sh
# API key read from macOS Keychain automatically
# Output: ~/.trace/tokenizer_ratio.json
# Log:    ~/.trace/tokenizer_check.log
```

Store your API key in Keychain once:

```bash
security add-generic-password -s ANTHROPIC_API_KEY -a anthropic -w sk-ant-...
```

**Remove:**

```bash
bash hooks/remove_tokenizer_check.sh
```

> **Note:** The wrapper script (`engine/tokenizer_check_wrapper.sh`) reads
> `ANTHROPIC_API_KEY` from macOS Keychain, so the key never needs to be set
> as a shell environment variable. Without a stored key the script exits
> cleanly without writing a ratio file; the dashboard silently shows no
> ratio row.

---

## Status line bridge

The status line bridge gives you a real-time context window and cost indicator directly in your terminal — updated after every Claude Code assistant message, including during long tool calls (more frequent than the Stop hook).

**What it shows:**

```
[sonnet-4-6] myproject | CTX: 42% | $0.12 | ● TRACE
```

| Field | Description |
|---|---|
| Model | Short model name: sonnet-4-6, opus-4-7, haiku-4-5 |
| Project | Name of your current working directory |
| CTX | Percentage of Claude Code's 200k context window — value sourced directly from Claude Code (official, not estimated); green < 60%, yellow 60–85%, red > 85% |
| Cost | Total session cost so far |
| ● TRACE | Shown when the TRACE dashboard is reachable; omitted if not running |

Updates are also sent to `http://localhost:8080/api/statusline` so the dashboard Context Window bar reflects the most recent turn in real-time — including during long tool calls, where the Stop hook does not fire until the full turn completes.

**Setup** (`trace.sh` → Option 7):

```bash
bash trace.sh           # → option 7: Setup status line bridge
# or directly:
bash hooks/setup_statusline_bridge.sh
```

**Requirements:** `jq` must be installed:

```bash
brew install jq
```

**Remove:**

```bash
bash trace.sh           # → option 8: Remove status line bridge
# or directly:
bash hooks/remove_statusline_bridge.sh
```

---

## Supported models

Prices are read from `trace_config.yaml` in the repo root at startup.
To add or adjust a model, edit the `models:` block there — no code changes needed.
Pull the repo on all machines to pick up the updated prices.
GPT models have been removed; TRACE tracks Claude Code sessions only.

| Model | Input per 1k tokens | Output per 1k tokens | Notes |
|---|---|---|---|
| claude-sonnet-4-6 | $0.003 | $0.015 | default / recommended |
| claude-sonnet-4-7 | $0.003 | $0.015 | |
| claude-sonnet-4-5 | $0.003 | $0.015 | |
| claude-opus-4-7 | $0.005 | $0.025 | highest capability |
| claude-opus-4-6 | $0.005 | $0.025 | |
| claude-opus-4-5 | $0.015 | $0.075 | |
| claude-haiku-4-5 | $0.0008 | $0.004 | lowest cost |

---

## Token count accuracy

> **TRACE vs `/context` – why the numbers differ**
>
> For **cost tracking**, TRACE sums `usage.input_tokens + cache_creation_input_tokens`
> per turn — this is the billable amount charged to your account.
> `cache_read_input_tokens` is intentionally excluded from the cost total because
> it re-counts the same cached context on every request and would inflate session
> totals many times over.
>
> For the **context window utilization bar**, TRACE uses
> `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` per turn
> (the peak across all turns). This correctly reflects how much of the model's
> context window was actually occupied for that API call.
>
> Claude Code's `/context` command shows the full context window
> breakdown (system prompt, tools, memory files, messages, autocompact
> buffer). This includes non-billable overhead not reflected in the API response.
>
> The numbers measure different things and will not match exactly.
> TRACE is the authoritative source for what you are actually charged.

> **Note on token count accuracy**
>
> TRACE reads token usage directly from Claude Code's
> session transcripts. The counts will be very close
> to your provider's billing figures but may differ
> slightly (typically 1–5%) because:
>
> - Providers apply their own system framing and
>   internal overhead not exposed in the transcript
> - Caching behaviour and token attribution varies
>   between providers and model versions
> - TRACE uses the transcript as its source of truth,
>   not the provider's billing API
>
> TRACE gives you a reliable **directional view** of
> your token consumption and costs – not a
> billing-grade exact replica. For authoritative
> figures, always refer to your provider's usage
> dashboard.
>
> If you consistently see large discrepancies (>10%),
> please open an issue – that may indicate a parsing
> bug worth fixing.

---

## Troubleshooting

> **Live session not showing in dashboard?**
> Make sure you have run `bash hooks/setup_claude_hook.sh`.
> Check with: `cat ~/.claude/settings.json`
> You should see both a `Stop` and a `SessionEnd` hook entry.

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
for common issues and solutions.

---

## License

MIT License – see LICENSE file.
