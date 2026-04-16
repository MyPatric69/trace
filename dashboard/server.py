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
from engine.live_tracker import LiveTracker
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

    # ── Live session (stale / missing → zeros) ────────────────────────────
    live_active = False
    live_input  = live_cc = live_cr = live_output = live_turns = 0
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
                live_turns  = int(live.get("turns",                 0))
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
        data = tracker.get_live()

        if data is None:
            # No active session – check for persisted health snapshot
            last_health = tracker.get_last_health()
            # Filter by project if requested
            if project and last_health and last_health.get("project") != project:
                last_health = None
            return {
                "active": False,
                "message": "No active session",
                "last_health": last_health,
            }

        if project and data.get("project") != project:
            active_in = data.get("project", "unknown")
            # Also include last_health for consistency
            last_health = tracker.get_last_health()
            if last_health and last_health.get("project") != project:
                last_health = None
            return {
                "active": False,
                "message": f"Active session is in project {active_in}",
                "last_health": last_health,
            }

        return {"active": True, **data}
    except Exception:
        return {"active": False, "message": "No active session", "last_health": None}


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
    """Read ~/.trace/trace_config.yaml; return (path, config_dict)."""
    path = TRACE_HOME / "trace_config.yaml"
    with open(path, encoding="utf-8") as f:
        return path, yaml.safe_load(f) or {}


def _save_and_sync_config(path: Path, config: dict) -> None:
    """Write updated config to *path* and sync to the project trace_config.yaml."""
    text = yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    # Sync to project trace_config.yaml (next to dashboard/)
    project = _DASHBOARD_DIR.parent / "trace_config.yaml"
    if project.exists():
        project.write_text(text, encoding="utf-8")


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
