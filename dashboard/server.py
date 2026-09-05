"""TRACE Web Dashboard – FastAPI server (v0.2.0).

Run with:
    bash dashboard/start.sh
    # or:
    python -m uvicorn dashboard.server:app --host 127.0.0.1 --port 8080 --reload
"""
import asyncio
import json
import os
import re
import sys
import urllib.error
import urllib.request
import yaml
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from engine.store import TraceStore, TRACE_HOME
from engine.live_tracker import LiveTracker, effective_context_thresholds
from engine.providers import get_provider
from engine.providers.manual import ManualProvider
from server.tools.context import check_drift, update_context
from server.tools.session import get_tips, new_session

# app is created after lifespan is defined — see bottom of this section


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Tracks active WebSocket connections and broadcasts messages to all."""

    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict) -> None:
        """Send *message* to every active connection; remove any that fail."""
        dead: list[WebSocket] = []
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()

# ---------------------------------------------------------------------------
# Provider cache – evaluated once per dashboard process, not per request
# ---------------------------------------------------------------------------

_provider: ManualProvider | None = None  # type: ignore[type-arg]
_provider_warned: bool = False


def _get_provider(config: dict):
    """Return a cached provider instance; call get_provider() at most once."""
    global _provider, _provider_warned
    if _provider is None:
        _provider = get_provider(config)
        configured = (config.get("api_integration") or {}).get("provider", "manual")
        if (
            not _provider_warned
            and isinstance(_provider, ManualProvider)
            and configured != "manual"
        ):
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "Provider '%s' unavailable – using manual fallback", configured
            )
            _provider_warned = True
    return _provider


# ---------------------------------------------------------------------------
# Background tasks (started on server startup)
# ---------------------------------------------------------------------------

async def _watch_live_file() -> None:
    """Broadcast 'live_updated' whenever any file in the live/ directory changes."""
    from engine.live_tracker import _LIVE_DIR as _LIVE_DIR_PATH
    last_sig = ""
    while True:
        await asyncio.sleep(1)
        try:
            mtimes: list[float] = []
            if _LIVE_DIR_PATH.is_dir():
                for f in _LIVE_DIR_PATH.glob("*.json"):
                    try:
                        mtimes.append(f.stat().st_mtime)
                    except OSError:
                        pass
            # Legacy fallback
            p = TRACE_HOME / "live_session.json"
            if p.exists():
                mtimes.append(p.stat().st_mtime)
            sig = str(sorted(mtimes))
            if sig != last_sig:
                last_sig = sig
                await manager.broadcast({
                    "type":      "live_updated",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "data":      None,
                })
        except Exception:
            pass


async def _watch_db() -> None:
    """Broadcast 'session_logged' whenever trace.db mtime changes."""
    last_mtime = 0.0
    first = True
    while True:
        await asyncio.sleep(1)
        try:
            db_path = TRACE_HOME / "trace.db"
            mtime = db_path.stat().st_mtime if db_path.exists() else 0.0
            if mtime != last_mtime:
                if not first:
                    await manager.broadcast({
                        "type":      "session_logged",
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "data":      None,
                    })
                last_mtime = mtime
                first = False
        except Exception:
            pass


async def _ping_clients() -> None:
    """Send keepalive ping to all clients every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        await manager.broadcast({
            "type":      "ping",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "data":      None,
        })


@asynccontextmanager
async def _lifespan(app: FastAPI):
    tasks = [
        asyncio.create_task(_watch_live_file()),
        asyncio.create_task(_watch_db()),
        asyncio.create_task(_ping_clients()),
    ]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="TRACE Dashboard", version="0.2.0", lifespan=_lifespan)

_DASHBOARD_DIR = Path(__file__).parent


def _store() -> TraceStore:
    store = TraceStore.default()
    store.init_db()
    return store


def _since(period: str) -> str | None:
    today = date.today()
    match period:
        case "today":
            return today.isoformat()
        case "week":
            return (today - timedelta(days=7)).isoformat()
        case "month":
            return (today - timedelta(days=30)).isoformat()
        case _:
            return None


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------

@app.get("/favicon.svg")
async def favicon():
    return FileResponse(
        Path(__file__).parent / "favicon.svg",
        media_type="image/svg+xml"
    )


@app.get("/", response_class=FileResponse)
def index():
    return FileResponse(_DASHBOARD_DIR / "index.html")


# ---------------------------------------------------------------------------
# /api/status
# ---------------------------------------------------------------------------

@app.get("/api/status")
def api_status():
    store = _store()
    summary = store.get_cost_summary()
    projects = store.list_projects()
    budgets = store.config.get("budgets", {})
    cfg = store.config.get("trace", {})
    db_str = "~/.trace/trace.db"
    try:
        db_str = "~/" + str(store.db_path.relative_to(Path.home()))
    except ValueError:
        db_str = str(store.db_path)
    notif_cfg = store.config.get("notifications") or {}
    health_cfg = store.config.get("session_health", {})
    comparison_cfg = store.config.get("comparison", {})
    billing_cfg = store.config.get("billing", {})
    return {
        "trace_version": cfg.get("version", "0.1.0"),
        "db_path": db_str,
        "project_count": len(projects),
        "total_cost_alltime": summary["total_cost_usd"],
        "mcp_connected": True,
        "monthly_budget_usd": budgets.get("default_monthly_usd", 20.0),
        "alert_threshold_pct": budgets.get("alert_threshold_pct", 80),
        "notifications_enabled": notif_cfg.get("enabled", True),
        "notifications_sound": notif_cfg.get("sound", True),
        "warn_context_pct": health_cfg.get("warn_context_pct", 60),
        "critical_context_pct": health_cfg.get("critical_context_pct", 85),
        "baseline_model": comparison_cfg.get("baseline_model", "claude-sonnet-4-6"),
        "billing_mode": billing_cfg.get("mode", "api"),
    }


# ---------------------------------------------------------------------------
# /api/projects
# ---------------------------------------------------------------------------

@app.get("/api/projects")
def api_projects():
    return _store().list_projects()


# ---------------------------------------------------------------------------
# /api/costs
# ---------------------------------------------------------------------------

@app.get("/api/costs")
def api_costs_all(period: str = "all"):
    store = _store()
    since = _since(period)
    summary = store.get_cost_summary(since_date=since)
    return {**summary, "period": period, "project": "all"}


@app.get("/api/costs/{project_name}")
def api_costs_project(project_name: str, period: str = "all"):
    store = _store()
    since = _since(period)
    summary = store.get_cost_summary(project_name=project_name, since_date=since)
    return {**summary, "period": period, "project": project_name}


# ---------------------------------------------------------------------------
# /api/tokens  (for session health bar)
# ---------------------------------------------------------------------------

@app.get("/api/tokens")
def api_tokens(project: str | None = None, period: str = "today"):
    store = _store()
    since = _since(period)
    tokens = store.get_token_summary(project_name=project, since_date=since)
    health_cfg = store.config.get("session_health", {})
    # cache_read excluded from total: it re-counts cached context on every
    # request and inflates session totals far beyond the real context window size.
    total = (
        tokens["total_input_tokens"]
        + tokens["total_cache_creation_tokens"]
        + tokens["total_output_tokens"]
    )
    return {
        "period":                        period,
        "project":                       project or "all",
        "total_input_tokens":            tokens["total_input_tokens"],
        "total_cache_creation_tokens":   tokens["total_cache_creation_tokens"],
        "total_cache_read_tokens":       tokens["total_cache_read_tokens"],
        "total_output_tokens":           tokens["total_output_tokens"],
        "total_tokens":                  total,
        "warn_at":                       health_cfg.get("warn_tokens",        80_000),
        "reset_at":                      health_cfg.get("critical_tokens",    150_000),
    }


# ---------------------------------------------------------------------------
# /api/stats/{date}  (metrics for a specific day – used by day picker)
# ---------------------------------------------------------------------------

@app.get("/api/stats/{date}")
def api_stats(date: str, project: str | None = None):
    """Return metrics for a specific date (YYYY-MM-DD format).

    Filters sessions to exactly that day using since_date=date and until_date=date.
    Used by the dashboard day picker to show historical daily stats.
    """
    store = _store()

    tokens = store.get_token_summary(
        project_name=project, since_date=date, until_date=date
    )
    costs = store.get_cost_summary(
        project_name=project, since_date=date, until_date=date
    )

    return {
        "date": date,
        "input_tokens": tokens["total_input_tokens"],
        "cache_creation_tokens": tokens["total_cache_creation_tokens"],
        "cache_read_tokens": tokens["total_cache_read_tokens"],
        "output_tokens": tokens["total_output_tokens"],
        "turns": tokens["total_turns"],
        "cost_usd": costs["total_cost_usd"],
        "session_count": costs["session_count"],
    }


# ---------------------------------------------------------------------------
# /api/today  (combined DB + live session view for metric cards)
# ---------------------------------------------------------------------------

@app.get("/api/today")
def api_today(project: str | None = None):
    """Return today's DB sessions merged with any active live session.

    All live_* fields are 0 / False when no live session exists.
    total_* fields are DB + live combined so the metric cards always
    reflect the true cost for the day.
    """
    store = _store()
    today_date = _since("today")

    # ── DB totals for today ───────────────────────────────────────────────
    tokens  = store.get_token_summary(project_name=project, since_date=today_date)
    costs   = store.get_cost_summary(project_name=project,  since_date=today_date)

    db_input    = tokens["total_input_tokens"]
    db_cc       = tokens["total_cache_creation_tokens"]
    db_cr       = tokens["total_cache_read_tokens"]
    db_output   = tokens["total_output_tokens"]
    db_turns    = tokens["total_turns"]
    db_cost     = costs["total_cost_usd"]
    db_sessions = costs["session_count"]

    # ── Live sessions (stale / missing → zeros) ──────────────────────────
    live_active = False
    live_input  = live_cc = live_cr = live_output = live_turns = 0
    live_cost   = 0.0
    try:
        sessions = LiveTracker(None).get_all_active()
        matching = [s for s in sessions
                    if (project is None or s.get("project") == project)
                    and not s.get("stale")]
        if matching:
            live_active = True
            for s in matching:
                live_input  += int(s.get("input_tokens",          0))
                live_cc     += int(s.get("cache_creation_tokens", 0))
                live_cr     += int(s.get("cache_read_tokens",     0))
                live_output += int(s.get("output_tokens",         0))
                live_turns  += int(s.get("turns",                 0))
                live_cost   += float(s.get("cost_usd",            0.0))
    except Exception:
        pass

    return {
        # DB portion
        "input_tokens":          db_input,
        "cache_creation_tokens": db_cc,
        "cache_read_tokens":     db_cr,
        "output_tokens":         db_output,
        "cost_usd":              db_cost,
        "session_count":         db_sessions,
        "turns_total":           db_turns + live_turns,
        # Live portion
        "live_active":               live_active,
        "live_input_tokens":         live_input,
        "live_cache_creation_tokens": live_cc,
        "live_cache_read_tokens":    live_cr,
        "live_output_tokens":        live_output,
        "live_cost_usd":             live_cost,
        # Combined
        "total_cost_usd":      round(db_cost   + live_cost,   6),
        "total_input_tokens":  db_input  + live_input,
        "total_cache_tokens":  db_cc     + live_cc + db_cr + live_cr,
        "total_output_tokens": db_output + live_output,
    }


# ---------------------------------------------------------------------------
# /api/models  (cost breakdown per model – CSS bar chart)
# ---------------------------------------------------------------------------

@app.get("/api/models")
def api_models(period: str = "week", project: str | None = None):
    store = _store()
    since = _since(period)
    sessions = store.get_sessions(project_name=project, since_date=since, limit=1000)

    costs: dict[str, float] = {}
    counts: dict[str, int] = {}
    for s in sessions:
        m = s["model"]
        costs[m] = costs.get(m, 0.0) + s["cost_usd"]
        counts[m] = counts.get(m, 0) + 1

    models = [
        {"model": m, "total_cost": round(c, 6), "session_count": counts[m]}
        for m, c in sorted(costs.items(), key=lambda x: -x[1])
    ]
    return {"period": period, "models": models}


# ---------------------------------------------------------------------------
# /api/providers  (provider badges per project, derived from model strings)
# ---------------------------------------------------------------------------

def resolve_provider(model: str) -> str:
    """Map a model name to its AI provider: anthropic / openai / google / other."""
    if model.startswith("claude-"):
        return "anthropic"
    if (model.startswith("gpt-") or model.startswith("o1-")
            or model.startswith("o3-") or model.startswith("o4-")):
        return "openai"
    if model.startswith("gemini-") or model.startswith("gemma-"):
        return "google"
    return "other"


@app.get("/api/providers")
def api_providers():
    store = _store()
    thirty_days_ago = (date.today() - timedelta(days=30)).isoformat()
    today_str = date.today().isoformat()
    all_projects = store.list_projects()

    result_projects = []
    summary_providers: set[str] = set()

    for p in all_projects:
        sessions = store.get_sessions(
            project_name=p["name"], since_date=thirty_days_ago, limit=1000
        )
        distinct_models = sorted({s["model"] for s in sessions})
        providers = sorted({resolve_provider(m) for m in distinct_models})
        sessions_today = store.get_cost_summary(
            project_name=p["name"], since_date=today_str
        )["session_count"]

        summary_providers.update(providers)
        result_projects.append({
            "name":           p["name"],
            "providers":      providers,
            "models":         distinct_models,
            "sessions_today": sessions_today,
        })

    return {
        "summary":  sorted(summary_providers),
        "projects": result_projects,
    }


# ---------------------------------------------------------------------------
# /api/drift + /api/sync
# ---------------------------------------------------------------------------

@app.get("/api/drift/{project_name}")
def api_drift(project_name: str):
    try:
        return check_drift(project_name)
    except Exception as e:
        return {"status": "error", "project": project_name, "message": str(e)}


@app.get("/api/sync/{project_name}")
def api_sync(project_name: str):
    try:
        return update_context(project_name)
    except Exception as e:
        return {"status": "error", "project": project_name, "message": str(e)}


# ---------------------------------------------------------------------------
# /api/live  (live session – updated every response via Stop hook)
# ---------------------------------------------------------------------------

@app.get("/api/live")
def api_live(project: str | None = None):
    try:
        tracker = LiveTracker(None)
        sessions = tracker.get_all_active()
        last_health = tracker.get_last_health()

        if not sessions:
            if project and last_health and last_health.get("project") != project:
                last_health = None
            return {
                "active": False,
                "sessions": [],
                "message": "No active session",
                "last_health": last_health,
            }

        if project:
            filtered = [s for s in sessions if s.get("project") == project]
            if not filtered:
                if last_health and last_health.get("project") != project:
                    last_health = None
                return {
                    "active": False,
                    "sessions": [],
                    "message": f"No active session for project {project}",
                    "last_health": last_health,
                }
            return {"active": True, "sessions": filtered, "last_health": last_health}

        return {"active": True, "sessions": sessions, "last_health": last_health}
    except Exception:
        return {"active": False, "sessions": [], "message": "No active session", "last_health": None}


# ---------------------------------------------------------------------------
# /api/statusline  (real-time update from Claude Code status line bridge)
# ---------------------------------------------------------------------------

class StatuslineRequest(BaseModel):
    session_id: str = ""
    cwd: str = ""
    context_window_pct: float = 0.0
    context_window_size: int = 200_000
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = "unknown"
    session_duration_ms: int = 0
    api_duration_ms: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    project_dir: str = ""


@app.post("/api/statusline")
def api_statusline(req: StatuslineRequest):
    """Accept a real-time update from hooks/statusline_bridge.sh.

    Updates an existing live session file with the latest context window %,
    peak context tokens, and cost.  Creates a minimal session file when the
    PreToolUse hook hasn't fired yet for this session.  Always returns 200.
    """
    from engine.live_tracker import _LIVE_DIR

    try:
        session_id = req.session_id
        if not session_id:
            return {"status": "ok"}

        now = datetime.now().isoformat(timespec="seconds")
        _LIVE_DIR.mkdir(parents=True, exist_ok=True)
        session_file = _LIVE_DIR / f"{session_id}.json"

        peak = (
            req.input_tokens
            + req.cache_creation_input_tokens
            + req.cache_read_input_tokens
        )

        warn_pct, critical_pct = 60.0, 85.0
        try:
            health_cfg = _store().config.get("session_health", {})
            warn_pct     = float(health_cfg.get("warn_context_pct", 60))
            critical_pct = float(health_cfg.get("critical_context_pct", 85))
        except Exception:
            pass
        eff_warn_pct, eff_critical_pct = effective_context_thresholds(
            warn_pct, critical_pct, req.context_window_size
        )

        if session_file.exists():
            try:
                data = json.loads(session_file.read_text())
                existing_peak = int(data.get("peak_context_tokens", 0))
                data["context_window_pct"] = req.context_window_pct
                data["context_window_size"] = req.context_window_size
                data["effective_warn_context_pct"] = eff_warn_pct
                data["effective_critical_context_pct"] = eff_critical_pct
                data["peak_context_tokens"] = max(existing_peak, peak)
                data["cost_usd"] = req.cost_usd
                data["updated_at"] = now
                if req.session_duration_ms:
                    data["session_duration_ms"] = req.session_duration_ms
                if req.api_duration_ms:
                    data["api_duration_ms"] = req.api_duration_ms
                if req.lines_added:
                    data["lines_added"] = req.lines_added
                if req.lines_removed:
                    data["lines_removed"] = req.lines_removed
                session_file.write_text(json.dumps(data, indent=2))
            except Exception:
                pass
        else:
            project: str | None = None
            try:
                tracker = LiveTracker(req.cwd)
                project = tracker.project_name
            except Exception:
                pass
            if not project and req.project_dir:
                try:
                    tracker = LiveTracker(req.project_dir)
                    project = tracker.project_name
                except Exception:
                    pass
            if not project:
                cwd_or_dir = req.cwd or req.project_dir
                project = Path(cwd_or_dir).name if cwd_or_dir else "unknown"

            data = {
                "session_id":          session_id,
                "project":             project,
                "cwd":                 req.cwd,
                "input_tokens":        req.total_input_tokens,
                "cache_creation_tokens": 0,
                "cache_read_tokens":   0,
                "output_tokens":       req.total_output_tokens,
                "peak_context_tokens": peak,
                "context_window_size": req.context_window_size,
                "context_window_pct":  req.context_window_pct,
                "effective_warn_context_pct":     eff_warn_pct,
                "effective_critical_context_pct": eff_critical_pct,
                "cost_usd":            req.cost_usd,
                "model":               req.model,
                "turns":               0,
                "health":              "green",
                "initializing":        False,
                "last_byte_offset":    0,
                "updated_at":          now,
                "session_duration_ms": req.session_duration_ms,
                "api_duration_ms":     req.api_duration_ms,
                "lines_added":         req.lines_added,
                "lines_removed":       req.lines_removed,
            }
            session_file.write_text(json.dumps(data, indent=2))
    except Exception:
        pass

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# /api/live/clear  (manual clear – e.g. after a DB reset)
# ---------------------------------------------------------------------------

@app.post("/api/live/clear")
def api_live_clear():
    try:
        LiveTracker(None).clear()
        return {"cleared": True}
    except Exception:
        return {"cleared": False}


# ---------------------------------------------------------------------------
# /api/settings  (notification preferences)
# ---------------------------------------------------------------------------

_BILLING_MODES = {"api", "pro", "max"}

class SettingsRequest(BaseModel):
    notifications_enabled: bool | None = None
    notifications_sound: bool | None = None
    warn_tokens: int | None = None
    critical_tokens: int | None = None
    warn_context_pct: int | None = None
    critical_context_pct: int | None = None
    monthly_budget_usd: float | None = None
    baseline_model: str | None = None
    billing_mode: str | None = None


@app.post("/api/settings")
def api_settings_update(req: SettingsRequest):
    """Persist notification settings and health thresholds to ~/.trace/trace_config.yaml."""
    path, config = _load_central_config()
    notif = config.setdefault("notifications", {})
    if req.notifications_enabled is not None:
        notif["enabled"] = req.notifications_enabled
    if req.notifications_sound is not None:
        notif["sound"] = req.notifications_sound
    if req.warn_tokens is not None or req.critical_tokens is not None:
        health = config.setdefault("session_health", {})
        eff_warn = req.warn_tokens if req.warn_tokens is not None else health.get("warn_tokens", 80_000)
        eff_crit = req.critical_tokens if req.critical_tokens is not None else health.get("critical_tokens", 150_000)
        if eff_warn <= 0:
            raise HTTPException(status_code=400, detail="warn_tokens must be > 0")
        if eff_warn >= eff_crit:
            raise HTTPException(status_code=400, detail="warn_tokens must be < critical_tokens")
        if req.warn_tokens is not None:
            health["warn_tokens"] = req.warn_tokens
        if req.critical_tokens is not None:
            health["critical_tokens"] = req.critical_tokens
    if req.warn_context_pct is not None or req.critical_context_pct is not None:
        health = config.setdefault("session_health", {})
        eff_warn = (
            req.warn_context_pct
            if req.warn_context_pct is not None
            else health.get("warn_context_pct", 60)
        )
        eff_crit = (
            req.critical_context_pct
            if req.critical_context_pct is not None
            else health.get("critical_context_pct", 85)
        )
        if eff_warn <= 0 or eff_warn >= 100:
            raise HTTPException(status_code=400, detail="warn_context_pct must be between 1 and 99")
        if eff_crit <= 0 or eff_crit > 100:
            raise HTTPException(status_code=400, detail="critical_context_pct must be between 1 and 100")
        if eff_warn >= eff_crit:
            raise HTTPException(
                status_code=400,
                detail="warn_context_pct must be < critical_context_pct",
            )
        if req.warn_context_pct is not None:
            health["warn_context_pct"] = req.warn_context_pct
        if req.critical_context_pct is not None:
            health["critical_context_pct"] = req.critical_context_pct
    if req.monthly_budget_usd is not None:
        if req.monthly_budget_usd <= 0:
            raise HTTPException(status_code=400, detail="monthly_budget_usd must be > 0")
        budgets = config.setdefault("budgets", {})
        budgets["default_monthly_usd"] = req.monthly_budget_usd
    if req.baseline_model is not None:
        models_cfg = config.get("models", {})
        if req.baseline_model not in models_cfg:
            raise HTTPException(status_code=400, detail=f"Unknown model: {req.baseline_model}")
        comparison = config.setdefault("comparison", {})
        comparison["baseline_model"] = req.baseline_model
    if req.billing_mode is not None:
        if req.billing_mode not in _BILLING_MODES:
            raise HTTPException(status_code=400, detail=f"billing_mode must be one of: {sorted(_BILLING_MODES)}")
        billing = config.setdefault("billing", {})
        billing["mode"] = req.billing_mode
    _save_and_sync_config(path, config)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# /api/activity  (streaks, active days, heatmap)
# ---------------------------------------------------------------------------

@app.get("/api/activity")
def api_activity(project: str | None = None):
    store = _store()
    stats   = store.get_activity_stats(project_name=project)
    heatmap = store.get_heatmap_data(project_name=project)
    return {"stats": stats, "heatmap": heatmap}


# ---------------------------------------------------------------------------
# /api/efficiency  (cost efficiency vs. baseline model)
# ---------------------------------------------------------------------------

@app.get("/api/efficiency")
def api_efficiency(project: str | None = None, period: str = "week"):
    store = _store()
    since = _since(period)
    sessions = store.get_sessions(project_name=project, since_date=since, limit=1000)

    models_cfg = store.config.get("models", {})
    comparison_cfg = store.config.get("comparison", {})
    baseline_model = comparison_cfg.get("baseline_model", "claude-sonnet-4-6")

    baseline_prices = models_cfg.get(baseline_model, {})
    baseline_input = baseline_prices.get("input_per_1k", 0.003)
    baseline_cc    = baseline_prices.get("cache_creation_per_1k", 0.00375)
    baseline_cr    = baseline_prices.get("cache_read_per_1k", 0.0003)
    baseline_output = baseline_prices.get("output_per_1k", 0.015)

    actual_cost = 0.0
    baseline_cost = 0.0
    model_counts: dict[str, int] = {}

    for s in sessions:
        actual_cost += s.get("cost_usd", 0.0) or 0.0
        input_t  = s.get("input_tokens", 0) or 0
        cc_t     = s.get("cache_creation_tokens", 0) or 0
        cr_t     = s.get("cache_read_tokens", 0) or 0
        output_t = s.get("output_tokens", 0) or 0
        baseline_cost += (
            input_t  * baseline_input  / 1000
            + cc_t   * baseline_cc     / 1000
            + cr_t   * baseline_cr     / 1000
            + output_t * baseline_output / 1000
        )
        m = s.get("model") or "unknown"
        model_counts[m] = model_counts.get(m, 0) + 1

    actual_model = max(model_counts, key=lambda k: model_counts[k]) if model_counts else "unknown"
    savings = round(baseline_cost - actual_cost, 6)

    return {
        "actual_cost":    round(actual_cost, 6),
        "baseline_cost":  round(baseline_cost, 6),
        "savings":        savings,
        "actual_model":   actual_model,
        "baseline_model": baseline_model,
        "period":         period,
    }


# ---------------------------------------------------------------------------
# /api/tokenizer_ratio  (daily tokenizer ratio – written by engine/tokenizer_check.py)
# ---------------------------------------------------------------------------

@app.get("/api/tokenizer_ratio")
def api_tokenizer_ratio():
    path = TRACE_HOME / "tokenizer_ratio.json"
    if not path.exists():
        return {"ratio": 1.0, "checked_at": None}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"ratio": 1.0, "checked_at": None}


# ---------------------------------------------------------------------------
# /api/tips
# ---------------------------------------------------------------------------

@app.get("/api/tips")
def api_tips(project_name: str | None = None):
    try:
        return get_tips(project_name)
    except Exception as e:
        return {"status": "error", "tips": [], "message": str(e)}


# ---------------------------------------------------------------------------
# /api/new_session  (dry_run handoff)
# ---------------------------------------------------------------------------

@app.get("/api/new_session/{project_name}")
def api_new_session(project_name: str, dry_run: bool = True):
    try:
        return new_session(project_name, dry_run=dry_run)
    except Exception as e:
        return {"status": "error", "project": project_name, "message": str(e)}


# ---------------------------------------------------------------------------
# /api/provider  (provider status + usage via pluggable adapter)
# ---------------------------------------------------------------------------

@app.get("/api/provider")
def api_provider(period: str = "month"):
    try:
        store    = _store()
        provider = _get_provider(store.config)
        name     = provider.get_name()
        fallback = name == "manual" and (
            (store.config.get("api_integration") or {}).get("provider", "manual") != "manual"
        )
        usage = provider.get_usage(period)
        return {
            "provider":  name,
            "available": provider.is_available(),
            "usage":     usage,
            "fallback":  fallback,
        }
    except Exception as e:
        return {
            "provider":  "manual",
            "available": True,
            "usage":     {},
            "fallback":  True,
            "error":     str(e),
        }


# ---------------------------------------------------------------------------
# /api/mcp  (MCP server registry – config-backed, add/remove via dashboard)
# ---------------------------------------------------------------------------

_TOKENS_PER_SERVER = 300
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
_MCP_DISCLAIMER = (
    "Token overhead per MCP server is estimated from a fixed baseline of "
    "~300 tokens per server per API call. Actual costs vary and cannot be "
    "measured per-server without an API proxy. Use these figures for rough "
    "guidance only."
)


def _load_central_config() -> tuple[Path, dict]:
    """Read user config and merge with system model prices.

    Returns (user_config_path, merged_dict).  The merged dict contains:
    - ``models`` block from the repo's trace_config.yaml (system config, read-only)
    - User preferences from ~/.trace/user_config.yaml

    Falls back to the legacy trace_config.yaml when user_config.yaml is absent.
    """
    from engine.config import TraceConfig, _USER_DEFAULTS

    user_path = TRACE_HOME / "user_config.yaml"
    user_cfg: dict = {}
    if user_path.exists():
        try:
            with open(user_path, encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
        except Exception:
            pass

    if not user_cfg:
        legacy = TRACE_HOME / "trace_config.yaml"
        if legacy.exists():
            try:
                with open(legacy, encoding="utf-8") as f:
                    user_cfg = yaml.safe_load(f) or {}
            except Exception:
                pass

    system_path = TraceConfig._REPO_ROOT / "trace_config.yaml"
    system_cfg: dict = {}
    if system_path.exists():
        try:
            with open(system_path, encoding="utf-8") as f:
                system_cfg = yaml.safe_load(f) or {}
        except Exception:
            pass

    merged = dict(system_cfg)
    for key in _USER_DEFAULTS:
        # Always assign user keys so system config never leaks user settings
        merged[key] = user_cfg.get(key, _USER_DEFAULTS[key])

    return user_path, merged


def _save_and_sync_config(path: Path, config: dict) -> None:
    """Write user settings to user_config.yaml; system config is never written at runtime."""
    from engine.config import _USER_KEYS
    user_data = {k: config[k] for k in _USER_KEYS if k in config}
    text = yaml.dump(user_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")


def _build_mcp_response(config: dict) -> dict:
    """Build the standard /api/mcp response dict from a loaded config."""
    mcp_list = config.get("mcp_servers") or []
    servers = [
        {
            "name":             s["name"],
            "estimated_tokens": _TOKENS_PER_SERVER,
            "source":           "estimated",
        }
        for s in mcp_list
        if isinstance(s, dict) and s.get("name")
    ]
    total = len(servers) * _TOKENS_PER_SERVER

    monthly_cost = 0.0
    try:
        store = _store()
        seven_days_ago = (date.today() - timedelta(days=7)).isoformat()
        recent = store.get_sessions(since_date=seven_days_ago, limit=1000)
        avg_sessions_per_day = len(recent) / 7
        turns_list: list[int] = []
        for s in recent:
            notes = s.get("notes") or ""
            if "turn" in notes.lower():
                m = re.search(r"(\d+)\s+turn", notes, re.IGNORECASE)
                if m:
                    turns_list.append(int(m.group(1)))
        avg_turns = (sum(turns_list) / len(turns_list)) if turns_list else 10
        monthly_calls = avg_sessions_per_day * avg_turns * 30
        models_cfg = store.config.get("models", {})
        sonnet_price = (
            (models_cfg.get("claude-sonnet-4-6") or {}).get("input_per_1k")
            or (models_cfg.get("claude-sonnet-4-5") or {}).get("input_per_1k")
            or 0.003
        )
        monthly_cost = round((total / 1000) * sonnet_price * monthly_calls, 4)
    except Exception:
        pass

    return {
        "servers":                servers,
        "total_estimated_tokens": total,
        "monthly_cost_estimate":  monthly_cost,
        "disclaimer":             _MCP_DISCLAIMER,
    }


@app.get("/api/mcp")
def api_mcp_get():
    """Return MCP servers registered in ~/.trace/trace_config.yaml."""
    try:
        _, config = _load_central_config()
    except Exception:
        config = {}
    return _build_mcp_response(config)


class McpServerRequest(BaseModel):
    name: str


@app.post("/api/mcp", status_code=201)
def api_mcp_add(req: McpServerRequest):
    """Add a named MCP server to ~/.trace/trace_config.yaml."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Server name cannot be empty.")
    if not _NAME_RE.match(name):
        raise HTTPException(
            status_code=422,
            detail="Name must be lowercase alphanumeric and hyphens only (e.g. github, my-server).",
        )
    path, config = _load_central_config()
    servers = config.setdefault("mcp_servers", [])
    if any(isinstance(s, dict) and s.get("name") == name for s in servers):
        raise HTTPException(status_code=409, detail=f"Server '{name}' already exists.")
    servers.append({"name": name, "estimated_tokens": _TOKENS_PER_SERVER})
    _save_and_sync_config(path, config)
    return _build_mcp_response(config)


@app.delete("/api/mcp/{name}")
def api_mcp_remove(name: str):
    """Remove a named MCP server from ~/.trace/trace_config.yaml."""
    path, config = _load_central_config()
    servers = config.get("mcp_servers") or []
    new_servers = [s for s in servers if not (isinstance(s, dict) and s.get("name") == name)]
    if len(new_servers) == len(servers):
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found.")
    config["mcp_servers"] = new_servers
    _save_and_sync_config(path, config)
    return _build_mcp_response(config)


# ---------------------------------------------------------------------------
# /api/tokenize  (token count + cost estimate)
# ---------------------------------------------------------------------------

class TokenizeRequest(BaseModel):
    text: str
    model: str


@app.get("/api/tokenize/models")
def api_tokenize_models():
    """Return configured models and prices for the Token Calculator selector."""
    store = _store()
    models = store.config.get("models", {})
    return [{"id": name, **prices} for name, prices in models.items()]


@app.post("/api/tokenize")
def api_tokenize(req: TokenizeRequest):
    """Count tokens for *text* using *model*, with cost estimate.

    - claude-*: Anthropic count_tokens API (ANTHROPIC_API_KEY), fallback char approx
    - gpt-*:    OpenAI input_tokens API  (OPENAI_API_KEY),     fallback word approx
    - other:    char approximation (len / 3.5)
    """
    text  = req.text
    model = req.model

    # Load prices from config regardless of method (case-insensitive lookup)
    store      = _store()
    models_cfg = store.config.get("models", {})
    prices     = models_cfg.get(model) or models_cfg.get(model.lower()) or {}
    cost_per_1k = prices.get("input_per_1k", 0.0)

    # Empty / whitespace → zero, no API call
    if not text or not text.strip():
        return {
            "model":             model,
            "input_tokens":      0,
            "cost_estimate_usd": 0.0,
            "method":            "approximation",
            "cost_per_1k_input": cost_per_1k,
        }

    method       = "approximation"
    input_tokens = 0

    if model.startswith("claude"):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            try:
                payload = json.dumps({
                    "model":    model,
                    "messages": [{"role": "user", "content": text}],
                }).encode()
                request = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages/count_tokens",
                    data=payload,
                    headers={
                        "x-api-key":          api_key,
                        "anthropic-version":  "2023-06-01",
                        "content-type":       "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=3) as resp:
                    data = json.loads(resp.read())
                    input_tokens = int(data["input_tokens"])
                method = "api"
            except Exception:
                input_tokens = int(len(text) / 3.5)
        else:
            input_tokens = int(len(text) / 3.5)
    elif model.startswith("gpt"):
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            try:
                payload = json.dumps({
                    "model": model,
                    "input": text,
                }).encode()
                request = urllib.request.Request(
                    "https://api.openai.com/v1/responses/input_tokens",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type":  "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=3) as resp:
                    data = json.loads(resp.read())
                    input_tokens = int(data["input_tokens"])
                method = "api"
            except Exception:
                input_tokens = int(len(text.split()) * 1.3)
        else:
            input_tokens = int(len(text.split()) * 1.3)
    else:
        input_tokens = int(len(text) / 3.5)

    cost = (input_tokens / 1000) * cost_per_1k

    return {
        "model":             model,
        "input_tokens":      input_tokens,
        "cost_estimate_usd": round(cost, 6),
        "method":            method,
        "cost_per_1k_input": cost_per_1k,
    }


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Accept a WebSocket connection and keep it alive until the client leaves."""
    await manager.connect(websocket)
    try:
        while True:
            # Receive and discard any client-sent frames (keepalives etc.)
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)
