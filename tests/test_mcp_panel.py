"""Tests for v0.3.0 Feature 4 (refactored) – MCP Server Panel.

Endpoints under test:
  GET    /api/mcp          – list servers from trace_config.yaml
  POST   /api/mcp          – add a server (validate name, reject duplicates)
  DELETE /api/mcp/{name}   – remove a server (404 when unknown)

Isolation strategy:
  - monkeypatch TRACE_HOME → tmp_path (so _load_central_config reads tmp yaml)
  - monkeypatch _save_and_sync_config → only writes the central file (no project sync)
  - monkeypatch _store → tmp TraceStore (for monthly cost calc)
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import dashboard.server as srv
from dashboard.server import app, _TOKENS_PER_SERVER, _MCP_DISCLAIMER
from engine.store import TraceStore

_MODEL_PRICES = {
    "claude-sonnet-4-6": {
        "input_per_1k": 0.003,
        "output_per_1k": 0.015,
        "cache_creation_per_1k": 0.00375,
        "cache_read_per_1k": 0.0003,
    },
}

_BASE_CONFIG = {
    "trace":    {"db_path": "test.db", "version": "0.3.0"},
    "projects": [],
    "budgets":  {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
    "session_health":  {"warn_tokens": 80_000, "critical_tokens": 150_000},
    "models":   _MODEL_PRICES,
    "api_integration": {"provider": "manual"},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_store(tmp_path):
    cfg = tmp_path / "trace_config.yaml"
    cfg.write_text(yaml.dump(_BASE_CONFIG))
    store = TraceStore(str(cfg))
    store.init_db()
    return store


@pytest.fixture
def mcp_home(tmp_path, monkeypatch, tmp_store):
    """
    Redirect TRACE_HOME to tmp_path so _load_central_config reads/writes
    a temp yaml.  Also prevent _save_and_sync_config from touching the real
    project trace_config.yaml.
    """
    # Write a fresh central config with empty mcp_servers
    central = tmp_path / "trace_config.yaml"
    config = dict(_BASE_CONFIG)
    config["mcp_servers"] = []
    central.write_text(yaml.dump(config))

    monkeypatch.setattr(srv, "TRACE_HOME", tmp_path)

    # Skip project-sync in tests
    def _no_sync(path: Path, cfg: dict) -> None:
        text = yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False)
        path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(srv, "_save_and_sync_config", _no_sync)

    monkeypatch.setattr(srv, "_store", lambda: tmp_store)

    return tmp_path


@pytest.fixture
def client(mcp_home):
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/mcp
# ---------------------------------------------------------------------------

def test_get_mcp_returns_correct_structure(client):
    res = client.get("/api/mcp")
    assert res.status_code == 200
    data = res.json()
    assert "servers" in data
    assert "total_estimated_tokens" in data
    assert "monthly_cost_estimate" in data
    assert "disclaimer" in data


def test_get_mcp_empty_when_no_servers(client):
    data = client.get("/api/mcp").json()
    assert data["servers"] == []
    assert data["total_estimated_tokens"] == 0


def test_get_mcp_disclaimer_always_present(client):
    data = client.get("/api/mcp").json()
    assert data["disclaimer"] == _MCP_DISCLAIMER
    assert "300" in data["disclaimer"]


def test_get_mcp_total_tokens_scales_with_servers(client, mcp_home):
    # Seed two servers directly in the yaml
    cfg_path = mcp_home / "trace_config.yaml"
    config = yaml.safe_load(cfg_path.read_text())
    config["mcp_servers"] = [
        {"name": "trace",  "estimated_tokens": _TOKENS_PER_SERVER},
        {"name": "github", "estimated_tokens": _TOKENS_PER_SERVER},
    ]
    cfg_path.write_text(yaml.dump(config))

    data = client.get("/api/mcp").json()
    assert data["total_estimated_tokens"] == 2 * _TOKENS_PER_SERVER
    assert len(data["servers"]) == 2


def test_get_mcp_missing_key_treated_as_empty(client, mcp_home):
    # Remove mcp_servers key entirely
    cfg_path = mcp_home / "trace_config.yaml"
    config = yaml.safe_load(cfg_path.read_text())
    config.pop("mcp_servers", None)
    cfg_path.write_text(yaml.dump(config))

    data = client.get("/api/mcp").json()
    assert data["servers"] == []
    assert data["total_estimated_tokens"] == 0


# ---------------------------------------------------------------------------
# POST /api/mcp
# ---------------------------------------------------------------------------

def test_post_mcp_adds_server(client):
    res = client.post("/api/mcp", json={"name": "trace"})
    assert res.status_code == 201
    data = res.json()
    assert any(s["name"] == "trace" for s in data["servers"])


def test_post_mcp_returns_correct_server_fields(client):
    data = client.post("/api/mcp", json={"name": "github"}).json()
    server = next(s for s in data["servers"] if s["name"] == "github")
    assert server["estimated_tokens"] == _TOKENS_PER_SERVER
    assert server["source"] == "estimated"


def test_post_mcp_total_tokens_correct_after_add(client):
    client.post("/api/mcp", json={"name": "trace"})
    data = client.post("/api/mcp", json={"name": "github"}).json()
    assert data["total_estimated_tokens"] == 2 * _TOKENS_PER_SERVER


def test_post_mcp_rejects_duplicate_name(client):
    client.post("/api/mcp", json={"name": "trace"})
    res = client.post("/api/mcp", json={"name": "trace"})
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"]


def test_post_mcp_rejects_empty_name(client):
    res = client.post("/api/mcp", json={"name": ""})
    assert res.status_code == 422


def test_post_mcp_rejects_whitespace_only_name(client):
    res = client.post("/api/mcp", json={"name": "   "})
    assert res.status_code == 422


def test_post_mcp_rejects_uppercase_letters(client):
    res = client.post("/api/mcp", json={"name": "MyServer"})
    assert res.status_code == 422


def test_post_mcp_rejects_spaces_in_name(client):
    res = client.post("/api/mcp", json={"name": "my server"})
    assert res.status_code == 422


def test_post_mcp_accepts_hyphenated_name(client):
    res = client.post("/api/mcp", json={"name": "my-server"})
    assert res.status_code == 201
    data = res.json()
    assert any(s["name"] == "my-server" for s in data["servers"])


def test_post_mcp_persists_to_yaml(client, mcp_home):
    client.post("/api/mcp", json={"name": "trace"})
    saved = yaml.safe_load((mcp_home / "trace_config.yaml").read_text())
    names = [s["name"] for s in saved.get("mcp_servers", [])]
    assert "trace" in names


# ---------------------------------------------------------------------------
# DELETE /api/mcp/{name}
# ---------------------------------------------------------------------------

def test_delete_mcp_removes_server(client):
    client.post("/api/mcp", json={"name": "trace"})
    res = client.delete("/api/mcp/trace")
    assert res.status_code == 200
    data = res.json()
    assert all(s["name"] != "trace" for s in data["servers"])


def test_delete_mcp_returns_updated_list(client):
    client.post("/api/mcp", json={"name": "trace"})
    client.post("/api/mcp", json={"name": "github"})
    data = client.delete("/api/mcp/trace").json()
    names = [s["name"] for s in data["servers"]]
    assert "trace" not in names
    assert "github" in names


def test_delete_mcp_unknown_returns_404(client):
    res = client.delete("/api/mcp/does-not-exist")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"]


def test_delete_mcp_persists_removal_to_yaml(client, mcp_home):
    client.post("/api/mcp", json={"name": "trace"})
    client.delete("/api/mcp/trace")
    saved = yaml.safe_load((mcp_home / "trace_config.yaml").read_text())
    names = [s["name"] for s in saved.get("mcp_servers", [])]
    assert "trace" not in names


def test_delete_mcp_total_tokens_decreases(client):
    client.post("/api/mcp", json={"name": "trace"})
    client.post("/api/mcp", json={"name": "github"})
    data = client.delete("/api/mcp/trace").json()
    assert data["total_estimated_tokens"] == _TOKENS_PER_SERVER


# ---------------------------------------------------------------------------
# disclaimer – always present
# ---------------------------------------------------------------------------

def test_disclaimer_present_on_get(client):
    assert client.get("/api/mcp").json()["disclaimer"] == _MCP_DISCLAIMER


def test_disclaimer_present_on_post(client):
    assert client.post("/api/mcp", json={"name": "trace"}).json()["disclaimer"] == _MCP_DISCLAIMER


def test_disclaimer_present_on_delete(client):
    client.post("/api/mcp", json={"name": "trace"})
    assert client.delete("/api/mcp/trace").json()["disclaimer"] == _MCP_DISCLAIMER
