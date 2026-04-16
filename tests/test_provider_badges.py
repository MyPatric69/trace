"""Tests for provider badge feature: resolve_provider() and GET /api/providers."""
import sqlite3
from datetime import date, timedelta

import pytest
import yaml
from fastapi.testclient import TestClient

import dashboard.server as dashboard_module
from dashboard.server import app, resolve_provider
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
        "session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000},
        "models":  _MODEL_PRICES,
    }
    cfg = tmp_path / "trace_config.yaml"
    cfg.write_text(yaml.dump(config))
    store = TraceStore(str(cfg))
    store.init_db()
    store.add_project("trace",  "/projects/trace",  "Trace project")
    store.add_project("webapp", "/projects/webapp", "Web app project")
    return store


@pytest.fixture
def client(tmp_store, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_store", lambda: tmp_store)
    return TestClient(app)


# ---------------------------------------------------------------------------
# resolve_provider()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model,expected", [
    # Anthropic
    ("claude-sonnet-4-5",  "anthropic"),
    ("claude-3-haiku",     "anthropic"),
    ("claude-opus-4-6",    "anthropic"),
    # OpenAI – gpt-*
    ("gpt-4o",             "openai"),
    ("gpt-4o-mini",        "openai"),
    ("gpt-3.5-turbo",      "openai"),
    # OpenAI – o1-* / o3-* / o4-*
    ("o1-preview",         "openai"),
    ("o1-mini",            "openai"),
    ("o3-mini",            "openai"),
    ("o4-turbo",           "openai"),
    # Google – gemini-* / gemma-*
    ("gemini-1.5-pro",     "google"),
    ("gemini-flash",       "google"),
    ("gemma-7b",           "google"),
    ("gemma-2b",           "google"),
    # Other
    ("llama-3-70b",        "other"),
    ("mistral-7b",         "other"),
    ("mixtral-8x7b",       "other"),
    ("some-unknown-model", "other"),
])
def test_resolve_provider_all_prefixes(model, expected):
    assert resolve_provider(model) == expected


# ---------------------------------------------------------------------------
# GET /api/providers – response structure
# ---------------------------------------------------------------------------

def test_api_providers_returns_200(client):
    res = client.get("/api/providers")
    assert res.status_code == 200


def test_api_providers_top_level_keys(client):
    data = client.get("/api/providers").json()
    assert "summary"  in data
    assert "projects" in data
    assert isinstance(data["summary"],  list)
    assert isinstance(data["projects"], list)


def test_api_providers_project_keys(client, tmp_store):
    tmp_store.add_session("trace", "claude-sonnet-4-5", 1000, 500)
    data = client.get("/api/providers").json()
    project = next(p for p in data["projects"] if p["name"] == "trace")
    for key in ("name", "providers", "models", "sessions_today"):
        assert key in project, f"Missing key: {key}"


def test_api_providers_summary_contains_provider(client, tmp_store):
    tmp_store.add_session("trace", "claude-sonnet-4-5", 1000, 500)
    data = client.get("/api/providers").json()
    assert "anthropic" in data["summary"]


def test_api_providers_correct_provider_for_claude(client, tmp_store):
    tmp_store.add_session("trace", "claude-sonnet-4-5", 1000, 500)
    data = client.get("/api/providers").json()
    project = next(p for p in data["projects"] if p["name"] == "trace")
    assert project["providers"] == ["anthropic"]
    assert "claude-sonnet-4-5" in project["models"]


def test_api_providers_sessions_today_count(client, tmp_store):
    tmp_store.add_session("trace", "claude-sonnet-4-5", 1000, 500)
    tmp_store.add_session("trace", "claude-sonnet-4-5", 2000, 800)
    data = client.get("/api/providers").json()
    project = next(p for p in data["projects"] if p["name"] == "trace")
    assert project["sessions_today"] == 2


# ---------------------------------------------------------------------------
# Multi-provider project
# ---------------------------------------------------------------------------

def test_multi_provider_project_shows_both_providers(client, tmp_store):
    """A project with claude + gpt sessions exposes both providers."""
    tmp_store.add_session("trace", "claude-sonnet-4-5", 1000, 500)
    tmp_store.add_session("trace", "gpt-4o",            2000, 1000)
    data = client.get("/api/providers").json()
    project = next(p for p in data["projects"] if p["name"] == "trace")
    assert set(project["providers"]) == {"anthropic", "openai"}
    assert "claude-sonnet-4-5" in project["models"]
    assert "gpt-4o"            in project["models"]


def test_multi_provider_summary_covers_all_projects(client, tmp_store):
    """Summary is the union of providers from every project."""
    tmp_store.add_session("trace",  "claude-sonnet-4-5", 1000, 500)
    tmp_store.add_session("webapp", "gpt-4o",            2000, 1000)
    data = client.get("/api/providers").json()
    assert set(data["summary"]) == {"anthropic", "openai"}


def test_providers_deduplicated_within_project(client, tmp_store):
    """Multiple sessions using the same model → only one provider badge."""
    tmp_store.add_session("trace", "claude-sonnet-4-5", 1000, 500)
    tmp_store.add_session("trace", "claude-sonnet-4-5", 2000, 800)
    data = client.get("/api/providers").json()
    project = next(p for p in data["projects"] if p["name"] == "trace")
    assert project["providers"].count("anthropic") == 1
    assert project["models"].count("claude-sonnet-4-5") == 1


# ---------------------------------------------------------------------------
# Projects with no recent sessions still appear
# ---------------------------------------------------------------------------

def test_all_projects_appear_even_with_no_sessions(client):
    """All registered projects show up even when there are no sessions at all."""
    data = client.get("/api/providers").json()
    names = {p["name"] for p in data["projects"]}
    assert "trace"  in names
    assert "webapp" in names


def test_project_with_no_sessions_has_empty_providers(client):
    """Projects with no sessions have providers=[] and models=[]."""
    data = client.get("/api/providers").json()
    for p in data["projects"]:
        assert p["providers"]      == []
        assert p["models"]         == []
        assert p["sessions_today"] == 0


def test_project_with_old_sessions_excluded_from_30day_window(tmp_store, monkeypatch):
    """Sessions older than 30 days are not included in providers/models."""
    old_date = (date.today() - timedelta(days=40)).isoformat()
    project  = tmp_store.get_project("trace")
    with sqlite3.connect(tmp_store.db_path) as conn:
        conn.execute(
            """INSERT INTO sessions
               (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, ?, 'claude-sonnet-4-5', 500, 200, 0.005)""",
            (project["id"], old_date),
        )

    monkeypatch.setattr(dashboard_module, "_store", lambda: tmp_store)
    data = TestClient(app).get("/api/providers").json()

    trace_entry = next(p for p in data["projects"] if p["name"] == "trace")
    assert trace_entry["models"]    == []
    assert trace_entry["providers"] == []
    # But the project row itself still exists
    assert trace_entry["name"] == "trace"
