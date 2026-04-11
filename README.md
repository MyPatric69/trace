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

## License

MIT License – see LICENSE file.
