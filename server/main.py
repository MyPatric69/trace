import sys
from pathlib import Path

# Ensure project root is on sys.path when running as `python server/main.py`
sys.path.insert(0, str(Path(__file__).parents[1]))

from fastmcp import FastMCP

from server.tools.costs import log_session as _log_session
from server.tools.costs import get_costs as _get_costs

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


if __name__ == "__main__":
    app.run()
