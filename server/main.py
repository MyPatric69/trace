from fastmcp import FastMCP

app = FastMCP("trace")


@app.tool()
def log_session(
    project: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    notes: str = "",
) -> str:
    """Log a session's token usage and cost for a project."""
    return "Phase 1 – coming soon"


@app.tool()
def get_costs(project: str | None = None) -> str:
    """Get cost summary for a project or all projects."""
    return "Phase 1 – coming soon"


if __name__ == "__main__":
    app.run()
