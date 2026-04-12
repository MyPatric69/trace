"""TRACE Web Dashboard – FastAPI server (v0.2.0).

Run with:
    bash dashboard/start.sh
    # or:
    python -m uvicorn dashboard.server:app --host 127.0.0.1 --port 8080 --reload
"""
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
    db_cost     = costs["total_cost_usd"]
    db_sessions = costs["session_count"]

    # ── Live session (stale / missing → zeros) ────────────────────────────
    live_active = False
    live_input  = live_cc = live_cr = live_output = 0
    live_cost   = 0.0
    try:
        live = LiveTracker(None).get_live()
        if live is not None:
            # Filter by project if requested
            if project is None or live.get("project") == project:
                live_active = True
                live_input  = int(live.get("input_tokens",          0))
                live_cc     = int(live.get("cache_creation_tokens", 0))
                live_cr     = int(live.get("cache_read_tokens",     0))
                live_output = int(live.get("output_tokens",         0))
                live_cost   = float(live.get("cost_usd",            0.0))
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
