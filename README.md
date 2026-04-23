# TRACE

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue) ![MIT License](https://img.shields.io/badge/license-MIT-green) ![MCP Server](https://img.shields.io/badge/MCP-server-lightgrey)

TRACE is a local MCP server that tracks token costs and keeps `AI_CONTEXT.md` automatically up to date across all your projects.

[→ Why TRACE exists (Technical Manifest)](docs/manifest_en.html)

---

## What TRACE does

**Token cost tracking.** Every AI session is logged with model, input tokens, output tokens, and calculated cost. TRACE aggregates this per project and period, surfaces budget alerts when monthly spend approaches the configured limit, and returns actionable optimisation tips when sessions run expensive.

**Context intelligence.** A post-commit hook watches every git commit and updates `AI_CONTEXT.md` automatically when doc-relevant files change. TRACE detects when the context file has drifted from the actual codebase, generates compressed handoff prompts so new sessions start fully oriented, and recommends session resets before token costs accelerate.

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

This creates `~/.trace/trace.db` and `~/.trace/trace_config.yaml` on first run.

**Step 3.6 – Install Claude Code hooks (required for live tracking):**

```bash
bash hooks/setup_claude_hook.sh
```

This installs two hooks into `~/.claude/settings.json`:

- **Stop hook** – updates live token counts after every turn
- **SessionEnd hook** – logs the final session cost to the database

Without this step, the live session panel and session cost tracking will not work.

> **Note:** If `~/.claude/settings.json` does not exist yet, the script creates it automatically. If it already exists, the hooks are added without overwriting existing settings.

**Step 4 – Add TRACE to your MCP config:**

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "trace": {
      "command": "python3",
      "args": ["/path/to/trace/server/main.py"]
    }
  }
}
```

Restart Claude Code after saving.

> **Using Claude Code without Claude Desktop?**
>
> If you only use Claude Code in the terminal (not the
> Claude Desktop app), skip Step 4 entirely.
> The `claude_desktop_config.json` is only needed for
> Claude Desktop integration.
>
> For Claude Code (terminal), the hooks installed in
> Step 3.6 are sufficient for full TRACE functionality:
> live session tracking, cost logging, and session health.
>
> You can still use TRACE MCP tools directly from Claude
> Code by adding TRACE to your project's
> `.claude/settings.json` or via `claude --mcp-config`.

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

After changing, sync to runtime config:
```bash
cp trace_config.yaml ~/.trace/trace_config.yaml
```

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

No credentials needed. Budget set via `monthly_budget_usd`
in `trace_config.yaml`.

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

**Session health thresholds**

Adjust when the session health indicator turns yellow or red.
Three presets are available – or enter custom values:

| Preset | Warning at | Critical at | For |
|---|---|---|---|
| Sparsam | 50,000 tokens | 100,000 tokens | Cost-conscious workflows |
| Standard | 80,000 tokens | 150,000 tokens | Default – recommended |
| Intensiv | 120,000 tokens | 200,000 tokens | Large projects / long sessions |

Settings are saved immediately to ~/.trace/trace_config.yaml.

> **Note:** The session health bar is only visible when a specific
> project is selected. Select your project from the dropdown in the
> header to see the health indicator for that project's active session.

### Session health thresholds

**Session health thresholds** are configured via the ⚙ Settings
popover in the dashboard header (see [Settings](#settings) above).
For power users, values can also be edited directly in
`~/.trace/trace_config.yaml`:

```yaml
session_health:
  warn_tokens: 80000     # yellow warning
  critical_tokens: 150000  # red critical
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

> **Note:** After every commit, TRACE automatically updates `AI_CONTEXT.md` via the post-commit hook. This is expected behaviour – not a bug. Stage and commit the change as part of your workflow:
>
> ```bash
> git add AI_CONTEXT.md
> git commit -m "chore: AI_CONTEXT.md auto-sync"
> ```

---

## CI/CD pipeline support (optional)

For teams using CI/CD pipelines, the hook can be installed automatically as part of the pipeline setup. For developers who prefer manual control or do not use pipelines, the manual install via `install_hook.sh` is fully supported and independent.

---

## Supported models

Prices are read from `~/.trace/trace_config.yaml` at startup. Adding a new model requires only a new entry in the `models:` block – no code changes.

| Model | Input per 1k tokens | Output per 1k tokens |
|---|---|---|
| claude-sonnet-4-5 | $0.003 | $0.015 |
| claude-opus-4-5 | $0.015 | $0.075 |
| claude-haiku-4-5 | $0.0008 | $0.004 |
| gpt-4o | $0.005 | $0.015 |
| gpt-4o-mini | $0.00015 | $0.0006 |

---

## Token count accuracy

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
