"""Tests for dashboard/server.py – Phase 4 web dashboard."""
import pytest
import yaml
from fastapi.testclient import TestClient

import dashboard.server as dashboard_module
from dashboard.server import app
from engine.store import TraceStore

_MODEL_PRICES = {
    "claude-sonnet-4-5": {"input_per_1k": 0.003, "output_per_1k": 0.015},
    "gpt-4o":            {"input_per_1k": 0.005, "output_per_1k": 0.015},
}


@pytest.fixture
def tmp_store(tmp_path):
    config = {
        "trace":   {"db_path": "test.db", "version": "0.1.0"},
        "projects": [],
        "budgets": {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
        "session": {"warn_at_tokens": 30_000, "recommend_reset_at": 50_000, "claude_autocompact_approx": 180_000},
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
    assert "30_000" in res.text or "30000" in res.text


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
        "projects": [], "budgets": {}, "session": {}, "models": {},
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
    for key in ("total_input_tokens", "total_output_tokens", "total_tokens", "warn_at", "reset_at"):
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
    assert data["warn_at"]  == 30_000
    assert data["reset_at"] == 50_000


def test_api_tokens_zero_when_no_sessions(client):
    data = client.get("/api/tokens").json()
    assert data["total_tokens"] == 0


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
