# TRACE

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue) ![MIT License](https://img.shields.io/badge/license-MIT-green) ![MCP Server](https://img.shields.io/badge/MCP-server-lightgrey)

TRACE is a local MCP server that tracks token costs and keeps `AI_CONTEXT.md` automatically up to date across all your projects.

[→ Why TRACE exists (Technical Manifest)](docs/manifest_en.html)

---

## What TRACE does

**Token cost tracking.** Every AI session is logged with model, input tokens, output tokens, and calculated cost. TRACE aggregates this per project and period, surfaces budget alerts when monthly spend approaches the configured limit, and returns actionable optimisation tips when sessions run expensive.

**Context intelligence.** A post-commit hook watches every git commit and updates `AI_CONTEXT.md` automatically when doc-relevant files change. TRACE detects when the context file has drifted from the actual codebase, generates compressed handoff prompts so new sessions start fully oriented, and recommends session resets before token costs accelerate.

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

**Step 5 – Register your first project:**

```python
python3 -c "
from engine.store import TraceStore
store = TraceStore.default()
store.init_db()
store.add_project('my-project', '/path/to/project', 'Description')
"
```

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

```bash
bash dashboard/start.sh
# → http://localhost:8080
```

Shows live token usage, costs, drift status, and recommendations for all projects.

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

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
for common issues and solutions.

---

## License

MIT License – see LICENSE file.
