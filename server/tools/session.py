"""Phase 3 MCP tools: new_session() and get_tips()."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from engine.context_compressor import ContextCompressor
from engine.store import TraceStore


def _store() -> TraceStore:
    store = TraceStore.default()
    store.init_db()
    return store


# ---------------------------------------------------------------------------
# new_session()
# ---------------------------------------------------------------------------

def new_session(project_name: str, dry_run: bool = False) -> dict:
    store = _store()
    project = store.get_project(project_name)
    if project is None:
        return {"status": "error", "message": f"Project not found: {project_name}"}

    project_path = project["path"]
    compressor = ContextCompressor(project_path, config_path=str(store.config_path))
    rec = compressor.get_session_recommendation()

    recommendation = rec["recommendation"]
    total_tokens = rec["total_tokens_today"]
    total_cost = rec["total_cost_today"]

    _message = {
        "continue": "Session is within healthy limits. No reset needed.",
        "warn": "Session approaching threshold. Consider starting fresh soon.",
        "reset": (
            "Session reset recommended. Handoff prompt ready – "
            "start a new chat with this context."
        ),
    }

    if recommendation == "continue" and not dry_run:
        return {
            "status": "not_needed",
            "project": project_name,
            "recommendation": recommendation,
            "total_tokens_today": total_tokens,
            "total_cost_today": total_cost,
            "handoff_prompt": "",
            "message": _message["continue"],
        }

    handoff_prompt = compressor.compress()

    if dry_run:
        return {
            "status": "dry_run",
            "project": project_name,
            "recommendation": recommendation,
            "total_tokens_today": total_tokens,
            "total_cost_today": total_cost,
            "handoff_prompt": handoff_prompt,
            "message": _message.get(recommendation, ""),
        }

    # Log a zero-token session marker
    try:
        store.add_session(project_name, "claude-sonnet-4-5", 0, 0, notes="session_reset")
    except ValueError:
        pass

    # Write handoff file (gitignored)
    handoff_path = Path(project_path) / ".trace_handoff.md"
    handoff_path.write_text(handoff_prompt, encoding="utf-8")

    return {
        "status": "ok",
        "project": project_name,
        "recommendation": recommendation,
        "total_tokens_today": total_tokens,
        "total_cost_today": total_cost,
        "handoff_prompt": handoff_prompt,
        "message": _message.get(recommendation, ""),
    }


# ---------------------------------------------------------------------------
# get_tips()
# ---------------------------------------------------------------------------

def get_tips(project_name: str | None = None) -> dict:
    store = _store()
    config = store.config

    today = date.today()
    seven_days_ago = (today - timedelta(days=7)).isoformat()
    three_days_ago = (today - timedelta(days=3)).isoformat()
    month_ago = (today - timedelta(days=30)).isoformat()

    sessions_7d = store.get_sessions(
        project_name=project_name, since_date=seven_days_ago, limit=200
    )
    sessions_3d = store.get_sessions(
        project_name=project_name, since_date=three_days_ago, limit=200
    )
    monthly_summary = store.get_cost_summary(
        project_name=project_name, since_date=month_ago
    )

    session_cfg = config.get("session", {})
    recommend_reset_at: int = session_cfg.get("recommend_reset_at", 50_000)
    budget_cfg = config.get("budgets", {})
    monthly_budget: float = budget_cfg.get("default_monthly_usd", 20.0)
    alert_pct: float = budget_cfg.get("alert_threshold_pct", 80)

    tips: list[str] = []
    total_cost_7d = sum(s["cost_usd"] for s in sessions_7d)
    session_count = len(sessions_7d)

    # Tip: high average session cost
    if session_count > 0:
        avg_cost = total_cost_7d / session_count
        if avg_cost > 0.50:
            tips.append(
                f"Consider shorter sessions – avg cost is ${avg_cost:.2f} per session"
            )

    # Tip: long sessions
    if any(s["input_tokens"] > recommend_reset_at for s in sessions_7d):
        tips.append("Long sessions detected – use new_session() earlier")

    # Tip: expensive model in use
    expensive_models = {"claude-opus-4-5", "gpt-4o"}
    models_used = {s["model"] for s in sessions_7d}
    if expensive_models & models_used:
        tips.append(
            "Consider claude-haiku-4-5 for routine tasks – 10x cheaper than Sonnet"
        )

    # Tip: no recent activity
    if not sessions_3d:
        tips.append(
            "No recent sessions tracked – remember to log sessions with log_session()"
        )

    # Tip: monthly budget alert
    monthly_cost = monthly_summary["total_cost_usd"]
    if monthly_budget > 0:
        pct = (monthly_cost / monthly_budget) * 100
        if pct >= alert_pct:
            tips.append(f"Monthly budget at {pct:.0f}% – review usage")

    most_expensive = (
        max(sessions_7d, key=lambda s: s["cost_usd"]) if sessions_7d else None
    )

    return {
        "project": project_name or "all",
        "period": "last_7_days",
        "total_cost": round(total_cost_7d, 6),
        "session_count": session_count,
        "tips": tips[:5],
        "most_expensive_session": most_expensive,
    }
