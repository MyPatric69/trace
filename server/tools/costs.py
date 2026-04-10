from datetime import date, timedelta
from pathlib import Path

from engine.store import TraceStore

# Resolve config relative to project root (two levels up from server/tools/)
_CONFIG_PATH = Path(__file__).parents[2] / "trace_config.yaml"


def _store() -> TraceStore:
    store = TraceStore(str(_CONFIG_PATH))
    store.init_db()
    return store


def _since_date(period: str) -> str | None:
    today = date.today()
    if period == "today":
        return today.isoformat()
    if period == "week":
        return (today - timedelta(days=7)).isoformat()
    if period == "month":
        return (today - timedelta(days=30)).isoformat()
    return None  # "all"


def log_session(
    project_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    notes: str = "",
) -> dict:
    try:
        session_id, cost_usd = _store().add_session(
            project_name, model, input_tokens, output_tokens, notes
        )
    except ValueError:
        return {"status": "error", "message": f"Project not found: {project_name}"}

    return {
        "status": "ok",
        "session_id": session_id,
        "cost_usd": cost_usd,
        "project": project_name,
        "model": model,
    }


def get_costs(
    project_name: str | None = None,
    period: str = "all",
) -> dict:
    store = _store()
    since = _since_date(period)

    summary = store.get_cost_summary(project_name=project_name, since_date=since)
    sessions = store.get_sessions(project_name=project_name, since_date=since)

    return {
        "project": project_name or "all",
        "period": period,
        "total_cost_usd": summary["total_cost"],
        "session_count": summary["session_count"],
        "avg_cost_per_session": summary["avg_cost_per_session"],
        "sessions": sessions,
    }
