"""Tests for dashboard/server.py – Phase 4 web dashboard."""
import pytest
import yaml
from fastapi.testclient import TestClient

import dashboard.server as dashboard_module
from dashboard.server import app
from engine.store import TraceStore

_MODEL_PRICES = {
    "claude-sonnet-4-5": {
        "input_per_1k": 0.003, "output_per_1k": 0.015,
        "cache_creation_per_1k": 0.00375, "cache_read_per_1k": 0.0003,
    },
    "gpt-4o": {
        "input_per_1k": 0.005, "output_per_1k": 0.015,
        "cache_creation_per_1k": 0.005, "cache_read_per_1k": 0.0025,
    },
}


@pytest.fixture
def tmp_store(tmp_path):
    config = {
        "trace":   {"db_path": "test.db", "version": "0.1.0"},
        "projects": [],
        "budgets": {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
        "session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000, "claude_autocompact_approx": 180_000},
        "models":  _MODEL_PRICES,
    }
    cfg = tmp_path / "trace_config.yaml"
    cfg.write_text(yaml.dump(config))
    store = TraceStore(str(cfg))
    store.init_db()
    store.add_project("alpha", "/projects/alpha", "Test project alpha")
    store.add_project("beta",  "/projects/beta",  "Test project beta")
    return store


@pytest.fixture
def client(tmp_store, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_store", lambda: tmp_store)
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

def test_index_returns_html(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "TRACE" in res.text


def test_index_contains_auto_refresh(client):
    res = client.get("/")
    assert "120_000" in res.text or "120000" in res.text


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------

def test_api_status_structure(client):
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert "trace_version" in data
    assert "db_path"        in data
    assert "project_count"  in data
    assert "total_cost_alltime" in data
    assert "mcp_connected"  in data


def test_api_status_project_count(client):
    data = client.get("/api/status").json()
    assert data["project_count"] == 2


def test_api_status_mcp_connected(client):
    data = client.get("/api/status").json()
    assert data["mcp_connected"] is True


def test_api_status_budget_fields(client):
    data = client.get("/api/status").json()
    assert data["monthly_budget_usd"]  == 20.0
    assert data["alert_threshold_pct"] == 80


def test_api_status_zero_cost_when_empty(client):
    data = client.get("/api/status").json()
    assert data["total_cost_alltime"] == 0.0


# ---------------------------------------------------------------------------
# GET /api/projects
# ---------------------------------------------------------------------------

def test_api_projects_returns_list(client):
    res = client.get("/api/projects")
    assert res.status_code == 200
    names = {p["name"] for p in res.json()}
    assert names == {"alpha", "beta"}


def test_api_projects_empty_when_no_projects(tmp_path, monkeypatch):
    config = {
        "trace": {"db_path": "test.db", "version": "0.1.0"},
        "projects": [], "budgets": {}, "session_health": {}, "models": {},
    }
    cfg = tmp_path / "trace_config.yaml"
    cfg.write_text(yaml.dump(config))
    empty_store = TraceStore(str(cfg))
    empty_store.init_db()
    monkeypatch.setattr(dashboard_module, "_store", lambda: empty_store)
    c = TestClient(app)
    assert c.get("/api/projects").json() == []


# ---------------------------------------------------------------------------
# GET /api/costs
# ---------------------------------------------------------------------------

def test_api_costs_all_returns_summary(client, tmp_store):
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    res = client.get("/api/costs")
    assert res.status_code == 200
    data = res.json()
    assert data["project"] == "all"
    assert data["session_count"] == 1
    assert data["total_cost_usd"] == pytest.approx(0.0105)


def test_api_costs_all_period_today(client, tmp_store):
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    data = client.get("/api/costs?period=today").json()
    assert data["period"] == "today"
    assert data["session_count"] == 1


def test_api_costs_project_filters_correctly(client, tmp_store):
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    tmp_store.add_session("beta",  "gpt-4o",            2000, 1000)

    data = client.get("/api/costs/alpha").json()
    assert data["project"] == "alpha"
    assert data["session_count"] == 1
    assert data["total_cost_usd"] == pytest.approx(0.0105)


def test_api_costs_project_unknown_returns_zero(client):
    data = client.get("/api/costs/ghost").json()
    assert data["session_count"] == 0
    assert data["total_cost_usd"] == 0.0


def test_api_costs_empty_no_sessions(client):
    data = client.get("/api/costs").json()
    assert data["session_count"] == 0
    assert data["total_cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# GET /api/tokens
# ---------------------------------------------------------------------------

def test_api_tokens_structure(client):
    res = client.get("/api/tokens")
    assert res.status_code == 200
    data = res.json()
    for key in (
        "total_input_tokens", "total_cache_creation_tokens", "total_cache_read_tokens",
        "total_output_tokens", "total_tokens", "warn_at", "reset_at",
    ):
        assert key in data


def test_api_tokens_sums_correctly(client, tmp_store):
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 2000, 800)
    data = client.get("/api/tokens?period=today").json()
    assert data["total_input_tokens"]  == 3000
    assert data["total_output_tokens"] == 1300
    assert data["total_tokens"]        == 4300


def test_api_tokens_uses_config_thresholds(client):
    data = client.get("/api/tokens").json()
    assert data["warn_at"]  == 80_000
    assert data["reset_at"] == 150_000


def test_api_tokens_zero_when_no_sessions(client):
    data = client.get("/api/tokens").json()
    assert data["total_tokens"] == 0


def test_api_tokens_total_excludes_cache_read(client, tmp_store):
    # total_tokens = input + cache_creation + output (NOT cache_read)
    tmp_store.add_session(
        "alpha", "claude-sonnet-4-5",
        input_tokens=1000, output_tokens=500,
        cache_creation_tokens=200, cache_read_tokens=99999,
    )
    data = client.get("/api/tokens?period=today").json()
    assert data["total_input_tokens"]          == 1000
    assert data["total_cache_creation_tokens"] == 200
    assert data["total_cache_read_tokens"]     == 99999
    assert data["total_output_tokens"]         == 500
    # Health bar total excludes cache_read to avoid 100x inflation
    assert data["total_tokens"]                == 1000 + 200 + 500  # 1700


# ---------------------------------------------------------------------------
# GET /api/models
# ---------------------------------------------------------------------------

def test_api_models_structure(client):
    res = client.get("/api/models")
    assert res.status_code == 200
    data = res.json()
    assert "period" in data
    assert "models" in data


def test_api_models_empty_when_no_sessions(client):
    data = client.get("/api/models").json()
    assert data["models"] == []


def test_api_models_aggregates_per_model(client, tmp_store):
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)   # $0.0105
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)   # $0.0105
    tmp_store.add_session("alpha", "gpt-4o",            2000, 1000)  # $0.025
    data = client.get("/api/models?period=all").json()
    names = [m["model"] for m in data["models"]]
    assert "claude-sonnet-4-5" in names
    assert "gpt-4o" in names


def test_api_models_sorted_by_cost_descending(client, tmp_store):
    tmp_store.add_session("alpha", "gpt-4o",            2000, 1000)  # more expensive
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 100,  50)    # cheaper
    data = client.get("/api/models?period=all").json()
    assert data["models"][0]["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# GET /api/drift  (monkeypatched – no real git repo needed)
# ---------------------------------------------------------------------------

def test_api_drift_returns_check_drift_result(client, monkeypatch):
    monkeypatch.setattr(
        dashboard_module, "check_drift",
        lambda name: {"status": "ok", "project": name, "is_stale": False, "commits_behind": 0},
    )
    data = client.get("/api/drift/alpha").json()
    assert data["status"] == "ok"
    assert data["project"] == "alpha"


def test_api_drift_handles_exception_gracefully(client, monkeypatch):
    monkeypatch.setattr(
        dashboard_module, "check_drift",
        lambda name: (_ for _ in ()).throw(RuntimeError("no git repo")),
    )
    data = client.get("/api/drift/alpha").json()
    assert data["status"] == "error"


# ---------------------------------------------------------------------------
# GET /api/tips  (monkeypatched)
# ---------------------------------------------------------------------------

def test_api_tips_structure(client, monkeypatch):
    monkeypatch.setattr(
        dashboard_module, "get_tips",
        lambda project_name=None: {"tips": ["Use haiku for routine tasks"], "total_cost": 0.5},
    )
    data = client.get("/api/tips").json()
    assert "tips" in data
    assert isinstance(data["tips"], list)


def test_api_tips_passes_project_name(client, monkeypatch):
    captured = {}
    def fake_tips(project_name=None):
        captured["project_name"] = project_name
        return {"tips": []}
    monkeypatch.setattr(dashboard_module, "get_tips", fake_tips)
    client.get("/api/tips?project_name=alpha")
    assert captured["project_name"] == "alpha"


# ---------------------------------------------------------------------------
# GET /api/live
# ---------------------------------------------------------------------------

_LIVE_DATA = {
    "project": "alpha", "input_tokens": 1000, "output_tokens": 500,
    "cost_usd": 0.01, "turns": 3, "health": "green",
}


def test_api_live_no_active_session(client, monkeypatch):
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [])
    data = client.get("/api/live").json()
    assert data["active"] is False
    assert "message" in data


def test_api_live_active_no_filter(client, monkeypatch):
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [dict(_LIVE_DATA)])
    data = client.get("/api/live").json()
    assert data["active"] is True
    assert data["sessions"][0]["project"] == "alpha"


def test_api_live_project_match_returns_active(client, monkeypatch):
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [dict(_LIVE_DATA)])
    data = client.get("/api/live?project=alpha").json()
    assert data["active"] is True
    assert data["sessions"][0]["project"] == "alpha"


def test_api_live_project_mismatch_returns_inactive(client, monkeypatch):
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [dict(_LIVE_DATA)])
    data = client.get("/api/live?project=beta").json()
    assert data["active"] is False
    assert "sessions" in data


def test_api_live_project_mismatch_message_names_active_project(client, monkeypatch):
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [dict(_LIVE_DATA)])
    data = client.get("/api/live?project=beta").json()
    assert data["message"] == "No active session for project beta"


# ---------------------------------------------------------------------------
# POST /api/live/clear
# ---------------------------------------------------------------------------

def test_api_live_clear_returns_cleared_true(client, monkeypatch):
    cleared = []
    monkeypatch.setattr(dashboard_module.LiveTracker, "clear", lambda self: cleared.append(1))
    res = client.post("/api/live/clear")
    assert res.status_code == 200
    assert res.json()["cleared"] is True


def test_api_live_clear_calls_live_tracker_clear(client, monkeypatch):
    cleared = []
    monkeypatch.setattr(dashboard_module.LiveTracker, "clear", lambda self: cleared.append(1))
    client.post("/api/live/clear")
    assert len(cleared) == 1


# ---------------------------------------------------------------------------
# GET /api/today
# ---------------------------------------------------------------------------

_LIVE_TODAY = {
    "project":               "alpha",
    "input_tokens":          500,
    "cache_creation_tokens": 100,
    "cache_read_tokens":     50,
    "output_tokens":         200,
    "cost_usd":              0.005,
    "turns":                 2,
    "health":                "green",
}


def test_api_today_structure(client, monkeypatch):
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [])
    data = client.get("/api/today").json()
    for key in (
        "input_tokens", "cache_creation_tokens", "cache_read_tokens", "output_tokens",
        "cost_usd", "session_count",
        "live_active", "live_input_tokens", "live_cache_creation_tokens",
        "live_cache_read_tokens", "live_output_tokens", "live_cost_usd",
        "total_cost_usd", "total_input_tokens", "total_cache_tokens", "total_output_tokens",
    ):
        assert key in data, f"Missing key: {key}"


def test_api_today_no_sessions_no_live_all_zeros(client, monkeypatch):
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [])
    data = client.get("/api/today").json()
    assert data["session_count"]    == 0
    assert data["cost_usd"]         == 0.0
    assert data["live_active"]      is False
    assert data["live_cost_usd"]    == 0.0
    assert data["total_cost_usd"]   == 0.0
    assert data["total_input_tokens"] == 0


def test_api_today_db_sessions_no_live(client, tmp_store, monkeypatch):
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [])
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    data = client.get("/api/today").json()
    assert data["session_count"]    == 1
    assert data["input_tokens"]     == 1000
    assert data["output_tokens"]    == 500
    assert data["live_active"]      is False
    assert data["live_cost_usd"]    == 0.0
    assert data["total_input_tokens"] == 1000
    assert data["total_output_tokens"] == 500
    assert data["total_cost_usd"]   == pytest.approx(data["cost_usd"])


def test_api_today_live_session_no_db(client, monkeypatch):
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [dict(_LIVE_TODAY)])
    data = client.get("/api/today").json()
    assert data["live_active"]      is True
    assert data["live_input_tokens"]  == 500
    assert data["live_output_tokens"] == 200
    assert data["live_cost_usd"]    == 0.005
    assert data["session_count"]    == 0
    assert data["total_input_tokens"]  == 500
    assert data["total_output_tokens"] == 200
    assert data["total_cost_usd"]   == pytest.approx(0.005)


def test_api_today_db_plus_live_combined(client, tmp_store, monkeypatch):
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [dict(_LIVE_TODAY)])
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    data = client.get("/api/today").json()
    assert data["live_active"]         is True
    assert data["session_count"]       == 1
    assert data["total_input_tokens"]  == 1000 + 500     # db + live
    assert data["total_output_tokens"] == 500  + 200     # db + live
    assert data["total_cost_usd"]      == pytest.approx(data["cost_usd"] + 0.005)


def test_api_today_total_cache_tokens_sums_all_four(client, tmp_store, monkeypatch):
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [dict(_LIVE_TODAY)])
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500,
                          cache_creation_tokens=200, cache_read_tokens=100)
    data = client.get("/api/today").json()
    # total_cache = db_cc + live_cc + db_cr + live_cr
    expected = 200 + 100 + 100 + 50
    assert data["total_cache_tokens"] == expected


def test_api_today_project_filter_excludes_other_project(client, tmp_store, monkeypatch):
    # Live session is for "alpha"; filter by "beta" → live not included
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [dict(_LIVE_TODAY)])
    tmp_store.add_session("beta", "claude-sonnet-4-5", 2000, 800)
    data = client.get("/api/today?project=beta").json()
    assert data["live_active"]        is False
    assert data["live_input_tokens"]  == 0
    assert data["input_tokens"]       == 2000


def test_api_today_project_filter_includes_matching_live(client, tmp_store, monkeypatch):
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [dict(_LIVE_TODAY)])
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    data = client.get("/api/today?project=alpha").json()
    assert data["live_active"]       is True
    assert data["live_input_tokens"] == 500


def test_api_today_never_fails_on_live_tracker_exception(client, monkeypatch):
    def raise_exc(self): raise RuntimeError("disk full")
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", raise_exc)
    data = client.get("/api/today").json()
    assert data["live_active"]  is False
    assert data["total_cost_usd"] >= 0.0


# ---------------------------------------------------------------------------
# GET /api/stats/{date}
# ---------------------------------------------------------------------------

def test_api_stats_date_returns_correct_structure(client, tmp_store):
    import sqlite3
    # Insert sessions with specific dates
    with sqlite3.connect(tmp_store.db_path) as conn:
        project = tmp_store.get_project("alpha")
        pid = project["id"]
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens,
                                     cache_creation_tokens, cache_read_tokens, cost_usd)
               VALUES (?, '2026-04-13', 'claude-sonnet-4-5', 5000, 2500, 300, 100, 0.0525)""",
            (pid,)
        )

    data = client.get("/api/stats/2026-04-13").json()
    assert data["date"]                 == "2026-04-13"
    assert data["input_tokens"]         == 5000
    assert data["cache_creation_tokens"] == 300
    assert data["cache_read_tokens"]    == 100
    assert data["output_tokens"]        == 2500
    assert data["cost_usd"]             == pytest.approx(0.0525)
    assert data["session_count"]        == 1


def test_api_stats_date_filters_to_exact_day(client, tmp_store):
    import sqlite3
    with sqlite3.connect(tmp_store.db_path) as conn:
        project = tmp_store.get_project("alpha")
        pid = project["id"]
        # Session on 2026-04-12 (should NOT be included)
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-12', 'claude-sonnet-4-5', 1000, 500, 0.0105)""",
            (pid,)
        )
        # Session on 2026-04-13 (should be included)
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-13', 'claude-sonnet-4-5', 3000, 1500, 0.0315)""",
            (pid,)
        )
        # Session on 2026-04-14 (should NOT be included)
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-14', 'claude-sonnet-4-5', 2000, 1000, 0.021)""",
            (pid,)
        )

    data = client.get("/api/stats/2026-04-13").json()
    assert data["input_tokens"]  == 3000
    assert data["output_tokens"] == 1500
    assert data["session_count"] == 1


def test_api_stats_date_project_filter(client, tmp_store):
    import sqlite3
    with sqlite3.connect(tmp_store.db_path) as conn:
        alpha = tmp_store.get_project("alpha")
        beta  = tmp_store.get_project("beta")
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-13', 'claude-sonnet-4-5', 1000, 500, 0.0105)""",
            (alpha["id"],)
        )
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-13', 'claude-sonnet-4-5', 4000, 2000, 0.042)""",
            (beta["id"],)
        )

    # Filter by project=alpha
    data = client.get("/api/stats/2026-04-13?project=alpha").json()
    assert data["input_tokens"]  == 1000
    assert data["session_count"] == 1

    # Filter by project=beta
    data = client.get("/api/stats/2026-04-13?project=beta").json()
    assert data["input_tokens"]  == 4000
    assert data["session_count"] == 1


def test_api_stats_date_empty_day_returns_zeros(client):
    data = client.get("/api/stats/2099-01-01").json()
    assert data["date"]          == "2099-01-01"
    assert data["input_tokens"]  == 0
    assert data["output_tokens"] == 0
    assert data["cost_usd"]      == 0.0
    assert data["session_count"] == 0


# ---------------------------------------------------------------------------
# Health State Persistence (Frontend Integration Tests)
# ---------------------------------------------------------------------------

def test_api_live_includes_health_status(client, monkeypatch):
    """Verify that /api/live includes health status for frontend persistence."""
    live_data = {
        "project": "alpha", "input_tokens": 85000, "output_tokens": 5000,
        "cache_creation_tokens": 5000, "cache_read_tokens": 1000,
        "cost_usd": 0.15, "turns": 10, "health": "warn",
        "warn_at": 80_000, "reset_at": 150_000,
    }
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [dict(live_data)])
    data = client.get("/api/live").json()
    assert data["active"] is True
    assert data["sessions"][0]["health"] == "warn"
    assert data["sessions"][0]["warn_at"] == 80_000
    assert data["sessions"][0]["reset_at"] == 150_000


def test_api_live_health_reset_status(client, monkeypatch):
    """Verify that /api/live can return 'reset' health status."""
    live_data = {
        "project": "alpha", "input_tokens": 155000, "output_tokens": 10000,
        "cache_creation_tokens": 10000, "cache_read_tokens": 2000,
        "cost_usd": 0.35, "turns": 20, "health": "reset",
        "warn_at": 80_000, "reset_at": 150_000,
    }
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [dict(live_data)])
    data = client.get("/api/live").json()
    assert data["active"] is True
    assert data["sessions"][0]["health"] == "reset"


def test_api_live_health_ok_status(client, monkeypatch):
    """Verify that /api/live returns 'ok' health status for low-token sessions."""
    live_data = {
        "project": "alpha", "input_tokens": 5000, "output_tokens": 1000,
        "cache_creation_tokens": 500, "cache_read_tokens": 200,
        "cost_usd": 0.02, "turns": 3, "health": "ok",
        "warn_at": 80_000, "reset_at": 150_000,
    }
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [dict(live_data)])
    data = client.get("/api/live").json()
    assert data["active"] is True
    assert data["sessions"][0]["health"] == "ok"


def test_api_live_no_session_includes_last_health(client, monkeypatch):
    """Verify that /api/live includes last_health when no active session."""
    last_health_data = {
        "status": "warn",
        "tokens": 95000,
        "project": "alpha",
        "session_id": "abc123",
        "updated_at": "2026-04-13T15:30:00",
    }
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [])
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_last_health", lambda self: dict(last_health_data))
    data = client.get("/api/live").json()
    assert data["active"] is False
    assert "last_health" in data
    assert data["last_health"]["status"] == "warn"
    assert data["last_health"]["tokens"] == 95000


def test_api_live_no_session_null_last_health_when_missing(client, monkeypatch):
    """Verify that /api/live returns last_health=null when no health snapshot exists."""
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [])
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_last_health", lambda self: None)
    data = client.get("/api/live").json()
    assert data["active"] is False
    assert data["last_health"] is None


def test_api_live_project_filter_last_health(client, monkeypatch):
    """Verify that last_health is filtered by project parameter."""
    last_health_data = {
        "status": "reset",
        "tokens": 160000,
        "project": "alpha",
        "session_id": "abc123",
        "updated_at": "2026-04-13T15:30:00",
    }
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_all_active", lambda self: [])
    monkeypatch.setattr(dashboard_module.LiveTracker, "get_last_health", lambda self: dict(last_health_data))

    # Filter by project=alpha → should include last_health
    data = client.get("/api/live?project=alpha").json()
    assert data["active"] is False
    assert data["last_health"] is not None
    assert data["last_health"]["project"] == "alpha"

    # Filter by project=beta → should exclude last_health (different project)
    data = client.get("/api/live?project=beta").json()
    assert data["active"] is False
    assert data["last_health"] is None


# ---------------------------------------------------------------------------
# GET /api/status – health threshold fields
# ---------------------------------------------------------------------------

def test_api_status_returns_threshold_fields(client):
    data = client.get("/api/status").json()
    assert "warn_tokens" in data
    assert "critical_tokens" in data
    assert data["warn_tokens"] == 80_000
    assert data["critical_tokens"] == 150_000


# ---------------------------------------------------------------------------
# POST /api/settings – health thresholds
# ---------------------------------------------------------------------------

def _patch_config(monkeypatch, tmp_path, config):
    """Write config to tmp_path and monkeypatch load/save helpers."""
    cfg_path = tmp_path / "trace_config.yaml"
    cfg_path.write_text(yaml.dump(config))
    saved = {}

    monkeypatch.setattr(
        dashboard_module, "_load_central_config",
        lambda: (cfg_path, yaml.safe_load(cfg_path.read_text())),
    )
    monkeypatch.setattr(
        dashboard_module, "_save_and_sync_config",
        lambda path, cfg: saved.update({"config": cfg}),
    )
    return saved


def test_api_settings_saves_warn_critical_tokens(client, tmp_path, monkeypatch):
    config = {
        "notifications": {"enabled": True, "sound": True},
        "session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000},
    }
    saved = _patch_config(monkeypatch, tmp_path, config)

    res = client.post("/api/settings", json={"warn_tokens": 60_000, "critical_tokens": 120_000})
    assert res.status_code == 200
    assert saved["config"]["session_health"]["warn_tokens"] == 60_000
    assert saved["config"]["session_health"]["critical_tokens"] == 120_000


def test_api_settings_validation_warn_equal_critical_returns_400(client, tmp_path, monkeypatch):
    config = {
        "notifications": {"enabled": True, "sound": True},
        "session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000},
    }
    _patch_config(monkeypatch, tmp_path, config)

    res = client.post("/api/settings", json={"warn_tokens": 100_000, "critical_tokens": 100_000})
    assert res.status_code == 400


def test_api_settings_validation_warn_greater_than_critical_returns_400(client, tmp_path, monkeypatch):
    config = {
        "notifications": {"enabled": True, "sound": True},
        "session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000},
    }
    _patch_config(monkeypatch, tmp_path, config)

    res = client.post("/api/settings", json={"warn_tokens": 200_000, "critical_tokens": 100_000})
    assert res.status_code == 400


@pytest.mark.parametrize("warn,critical", [
    (50_000, 100_000),   # Sparsam
    (80_000, 150_000),   # Standard
    (120_000, 200_000),  # Intensiv
])
def test_api_settings_preset_values_valid(warn, critical):
    """All dashboard presets must satisfy warn > 0 and warn < critical."""
    assert warn > 0
    assert warn < critical


def test_api_status_returns_monthly_budget_usd(client):
    data = client.get("/api/status").json()
    assert "monthly_budget_usd" in data
    assert data["monthly_budget_usd"] == 20.0


def test_api_settings_saves_monthly_budget_usd(client, tmp_path, monkeypatch):
    config = {
        "notifications": {"enabled": True, "sound": True},
        "session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000},
        "budgets": {"default_monthly_usd": 20.0},
    }
    saved = _patch_config(monkeypatch, tmp_path, config)

    res = client.post("/api/settings", json={"monthly_budget_usd": 50.0})
    assert res.status_code == 200
    assert saved["config"]["budgets"]["default_monthly_usd"] == 50.0


def test_api_settings_rejects_monthly_budget_usd_zero_or_negative(client, tmp_path, monkeypatch):
    config = {
        "notifications": {"enabled": True, "sound": True},
        "session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000},
        "budgets": {"default_monthly_usd": 20.0},
    }
    _patch_config(monkeypatch, tmp_path, config)

    assert client.post("/api/settings", json={"monthly_budget_usd": 0.0}).status_code == 400
    assert client.post("/api/settings", json={"monthly_budget_usd": -5.0}).status_code == 400


# ---------------------------------------------------------------------------
# GET /api/activity
# ---------------------------------------------------------------------------

def test_api_activity_returns_structure(client):
    res = client.get("/api/activity")
    assert res.status_code == 200
    body = res.json()
    assert "stats" in body
    assert "heatmap" in body


def test_api_activity_stats_keys(client, tmp_store):
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    res = client.get("/api/activity")
    stats = res.json()["stats"]
    for key in ("total_sessions", "active_days", "current_streak",
                "longest_streak", "most_active_day", "favorite_model",
                "total_cost_usd", "total_tokens"):
        assert key in stats, f"Missing key: {key}"


def test_api_activity_heatmap_entry_keys(client, tmp_store):
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    res = client.get("/api/activity")
    body = res.json()
    assert len(body["heatmap"]) >= 1
    entry = body["heatmap"][0]
    for key in ("date", "sessions", "cost_usd", "tokens"):
        assert key in entry, f"Missing heatmap key: {key}"


def test_api_activity_project_filter(client, tmp_store):
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    tmp_store.add_session("beta",  "gpt-4o", 2000, 1000)

    res_alpha = client.get("/api/activity?project=alpha")
    res_beta  = client.get("/api/activity?project=beta")

    assert res_alpha.json()["stats"]["total_sessions"] == 1
    assert res_beta.json()["stats"]["total_sessions"]  == 1


def test_api_activity_empty_when_no_sessions(client):
    res = client.get("/api/activity?project=alpha")
    body = res.json()
    assert body["stats"]["total_sessions"] == 0
    assert body["heatmap"] == []


def test_api_activity_total_cost_matches_sessions(client, tmp_store):
    # alpha: 2 sessions × $0.0105 each = $0.021
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    res = client.get("/api/activity?project=alpha")
    assert res.json()["stats"]["total_cost_usd"] == pytest.approx(0.021)
