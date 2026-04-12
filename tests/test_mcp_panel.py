"""Tests for v0.3.0 Feature 4 – MCP Server Panel (GET /api/mcp).

Covers:
  - correct response structure
  - empty server list when settings.json is absent
  - disclaimer always present
  - total_estimated_tokens = n * 300
  - per-server fields (name, command, args, source)
  - monthly_cost_estimate calculation
  - resilience to malformed settings.json
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import dashboard.server as dashboard_module
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

_SAMPLE_SETTINGS = {
    "mcpServers": {
        "trace": {
            "command": "python3",
            "args": ["-m", "server.main"],
        },
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
        },
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        },
    }
}


@pytest.fixture
def tmp_store(tmp_path):
    config = {
        "trace":    {"db_path": "test.db", "version": "0.3.0"},
        "projects": [],
        "budgets":  {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
        "session":  {"warn_at_tokens": 30_000, "recommend_reset_at": 50_000},
        "models":   _MODEL_PRICES,
        "api_integration": {"provider": "manual"},
    }
    cfg = tmp_path / "trace_config.yaml"
    cfg.write_text(yaml.dump(config))
    store = TraceStore(str(cfg))
    store.init_db()
    return store


@pytest.fixture
def client(tmp_store, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_store", lambda: tmp_store)
    return TestClient(app)


def _settings(tmp_path, content: dict) -> Path:
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(content))
    return p


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_api_mcp_returns_correct_keys(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", _settings(tmp_path, _SAMPLE_SETTINGS))
    res = client.get("/api/mcp")
    assert res.status_code == 200
    data = res.json()
    assert "servers" in data
    assert "total_estimated_tokens" in data
    assert "monthly_cost_estimate" in data
    assert "disclaimer" in data


def test_api_mcp_server_fields(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", _settings(tmp_path, _SAMPLE_SETTINGS))
    data = client.get("/api/mcp").json()
    assert len(data["servers"]) == 3
    server = next(s for s in data["servers"] if s["name"] == "trace")
    assert server["command"] == "python3"
    assert server["args"] == ["-m", "server.main"]
    assert server["estimated_tokens"] == _TOKENS_PER_SERVER
    assert server["source"] == "estimated"


# ---------------------------------------------------------------------------
# Empty list when settings.json is absent
# ---------------------------------------------------------------------------

def test_api_mcp_empty_when_no_settings(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", tmp_path / "nonexistent.json")
    data = client.get("/api/mcp").json()
    assert data["servers"] == []
    assert data["total_estimated_tokens"] == 0


def test_api_mcp_still_returns_disclaimer_when_no_settings(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", tmp_path / "nonexistent.json")
    data = client.get("/api/mcp").json()
    assert data["disclaimer"] == _MCP_DISCLAIMER
    assert len(data["disclaimer"]) > 20


# ---------------------------------------------------------------------------
# Disclaimer always present
# ---------------------------------------------------------------------------

def test_disclaimer_always_present_with_servers(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", _settings(tmp_path, _SAMPLE_SETTINGS))
    data = client.get("/api/mcp").json()
    assert data["disclaimer"] == _MCP_DISCLAIMER


def test_disclaimer_text_mentions_300_tokens(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", _settings(tmp_path, _SAMPLE_SETTINGS))
    data = client.get("/api/mcp").json()
    assert "300" in data["disclaimer"]


# ---------------------------------------------------------------------------
# total_estimated_tokens = n * 300
# ---------------------------------------------------------------------------

def test_total_estimated_tokens_three_servers(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", _settings(tmp_path, _SAMPLE_SETTINGS))
    data = client.get("/api/mcp").json()
    assert data["total_estimated_tokens"] == 3 * _TOKENS_PER_SERVER


def test_total_estimated_tokens_one_server(client, tmp_path, monkeypatch):
    single = {"mcpServers": {"trace": {"command": "python3", "args": []}}}
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", _settings(tmp_path, single))
    data = client.get("/api/mcp").json()
    assert data["total_estimated_tokens"] == _TOKENS_PER_SERVER


def test_total_estimated_tokens_empty(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", _settings(tmp_path, {"mcpServers": {}}))
    data = client.get("/api/mcp").json()
    assert data["total_estimated_tokens"] == 0


# ---------------------------------------------------------------------------
# monthly_cost_estimate
# ---------------------------------------------------------------------------

def test_monthly_cost_estimate_is_float(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", _settings(tmp_path, _SAMPLE_SETTINGS))
    data = client.get("/api/mcp").json()
    assert isinstance(data["monthly_cost_estimate"], (int, float))


def test_monthly_cost_estimate_zero_when_no_sessions(client, tmp_path, monkeypatch):
    """With no sessions in the last 7 days, monthly cost should be 0."""
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", _settings(tmp_path, _SAMPLE_SETTINGS))
    data = client.get("/api/mcp").json()
    # tmp_store has no sessions → avg_sessions_per_day = 0 → cost = 0
    assert data["monthly_cost_estimate"] == 0.0


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------

def test_api_mcp_handles_malformed_json(client, tmp_path, monkeypatch):
    bad = tmp_path / "settings.json"
    bad.write_text("NOT VALID JSON{{{")
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", bad)
    res = client.get("/api/mcp")
    assert res.status_code == 200
    data = res.json()
    assert data["servers"] == []
    assert data["disclaimer"] == _MCP_DISCLAIMER


def test_api_mcp_handles_missing_mcpservers_key(client, tmp_path, monkeypatch):
    """settings.json present but no mcpServers key → empty list."""
    monkeypatch.setattr(dashboard_module, "_CLAUDE_SETTINGS", _settings(tmp_path, {"other": "data"}))
    data = client.get("/api/mcp").json()
    assert data["servers"] == []
    assert data["total_estimated_tokens"] == 0
