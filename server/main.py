import sys
from pathlib import Path

# Ensure project root is on sys.path when running as `python server/main.py`
sys.path.insert(0, str(Path(__file__).parents[1]))

from fastmcp import FastMCP

from server.tools.costs import log_session as _log_session
from server.tools.costs import get_costs as _get_costs
from server.tools.context import check_drift as _check_drift
from server.tools.context import update_context as _update_context

app = FastMCP("trace")


@app.tool()
def log_session(
    project_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    notes: str = "",
) -> dict:
    """Log a session's token usage and automatically calculate its cost."""
    return _log_session(project_name, model, input_tokens, output_tokens, notes)


@app.tool()
def get_costs(
    project_name: str | None = None,
    period: str = "all",
) -> dict:
    """Get cost summary and session list. period: 'today' | 'week' | 'month' | 'all'."""
    return _get_costs(project_name, period)


@app.tool()
def check_drift(project_name: str) -> dict:
    """Check if AI_CONTEXT.md is stale relative to recent git commits."""
    return _check_drift(project_name)


@app.tool()
def update_context(project_name: str, dry_run: bool = False) -> dict:
    """Sync AI_CONTEXT.md with recent git commits. Use dry_run=True to preview."""
    return _update_context(project_name, dry_run)


if __name__ == "__main__":
    app.run()
