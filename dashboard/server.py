"""TRACE Web Dashboard – FastAPI server (v0.2.0).

Run with:
    bash dashboard/start.sh
    # or:
    python -m uvicorn dashboard.server:app --host 127.0.0.1 --port 8080 --reload
"""
import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from engine.store import TraceStore, TRACE_HOME
from engine.live_tracker import LiveTracker
from engine.providers import get_provider
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
# Background tasks (started on server startup)
# ---------------------------------------------------------------------------

async def _watch_live_file() -> None:
    """Broadcast 'live_updated' whenever live_session.json mtime changes."""
    last_mtime = 0.0
    while True:
        await asyncio.sleep(1)
        try:
            p = TRACE_HOME / "live_session.json"
            mtime = p.stat().st_mtime if p.exists() else 0.0
            if mtime != last_mtime:
                last_mtime = mtime
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
    return {
        "trace_version": cfg.get("version", "0.1.0"),
        "db_path": db_str,
        "project_count": len(projects),
        "total_cost_alltime": summary["total_cost_usd"],
        "mcp_connected": True,
        "monthly_budget_usd": budgets.get("default_monthly_usd", 20.0),
        "alert_threshold_pct": budgets.get("alert_threshold_pct", 80),
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
    session_cfg = store.config.get("session", {})
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
        "warn_at":                       session_cfg.get("warn_at_tokens",        30_000),
        "reset_at":                      session_cfg.get("recommend_reset_at",    50_000),
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
        data = LiveTracker(None).get_live()
        if data is None:
            return {"active": False, "message": "No active session"}
        if project and data.get("project") != project:
            active_in = data.get("project", "unknown")
            return {"active": False, "message": f"Active session is in project {active_in}"}
        return {"active": True, **data}
    except Exception:
        return {"active": False, "message": "No active session"}


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
        provider = get_provider(store.config)
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
