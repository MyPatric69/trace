"""Tests for v0.3.0 Feature 4 – MCP Server Panel (GET /api/mcp).

Covers:
  - correct response structure
  - empty server list when both config files are absent
  - disclaimer always present
  - total_estimated_tokens = n * 300
  - per-server fields (name, command, args, source)
  - monthly_cost_estimate calculation
  - resilience to malformed files
  - dual-source merge: ~/.claude/settings.json +
    ~/Library/Application Support/Claude/claude_desktop_config.json
  - deduplication by name (settings.json wins on collision)
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


def _write(tmp_path: Path, name: str, content: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(content))
    return p


def _absent(tmp_path: Path, name: str = "absent.json") -> Path:
    return tmp_path / name  # does not exist


def _patch(monkeypatch, *, settings=None, desktop=None, tmp_path: Path):
    """Patch both MCP source paths. Pass None to leave as absent."""
    monkeypatch.setattr(
        dashboard_module, "_CLAUDE_SETTINGS",
        settings if settings is not None else _absent(tmp_path, "settings.json"),
    )
    monkeypatch.setattr(
        dashboard_module, "_CLAUDE_DESKTOP_CONFIG",
        desktop if desktop is not None else _absent(tmp_path, "desktop.json"),
    )


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_api_mcp_returns_correct_keys(client, tmp_path, monkeypatch):
    settings = _write(tmp_path, "settings.json", _SAMPLE_SETTINGS)
    _patch(monkeypatch, settings=settings, tmp_path=tmp_path)
    res = client.get("/api/mcp")
    assert res.status_code == 200
    data = res.json()
    assert "servers" in data
    assert "total_estimated_tokens" in data
    assert "monthly_cost_estimate" in data
    assert "disclaimer" in data


def test_api_mcp_server_fields(client, tmp_path, monkeypatch):
    settings = _write(tmp_path, "settings.json", _SAMPLE_SETTINGS)
    _patch(monkeypatch, settings=settings, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert len(data["servers"]) == 3
    server = next(s for s in data["servers"] if s["name"] == "trace")
    assert server["command"] == "python3"
    assert server["args"] == ["-m", "server.main"]
    assert server["estimated_tokens"] == _TOKENS_PER_SERVER
    assert server["source"] == "estimated"


# ---------------------------------------------------------------------------
# Empty list when both files are absent
# ---------------------------------------------------------------------------

def test_api_mcp_empty_when_both_absent(client, tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert data["servers"] == []
    assert data["total_estimated_tokens"] == 0


def test_api_mcp_empty_when_no_settings(client, tmp_path, monkeypatch):
    """Legacy: only settings path absent, desktop also absent."""
    _patch(monkeypatch, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert data["servers"] == []
    assert data["total_estimated_tokens"] == 0


def test_api_mcp_still_returns_disclaimer_when_both_absent(client, tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert data["disclaimer"] == _MCP_DISCLAIMER
    assert len(data["disclaimer"]) > 20


# ---------------------------------------------------------------------------
# Disclaimer always present
# ---------------------------------------------------------------------------

def test_disclaimer_always_present_with_servers(client, tmp_path, monkeypatch):
    settings = _write(tmp_path, "settings.json", _SAMPLE_SETTINGS)
    _patch(monkeypatch, settings=settings, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert data["disclaimer"] == _MCP_DISCLAIMER


def test_disclaimer_text_mentions_300_tokens(client, tmp_path, monkeypatch):
    settings = _write(tmp_path, "settings.json", _SAMPLE_SETTINGS)
    _patch(monkeypatch, settings=settings, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert "300" in data["disclaimer"]


# ---------------------------------------------------------------------------
# total_estimated_tokens = n * 300
# ---------------------------------------------------------------------------

def test_total_estimated_tokens_three_servers(client, tmp_path, monkeypatch):
    settings = _write(tmp_path, "settings.json", _SAMPLE_SETTINGS)
    _patch(monkeypatch, settings=settings, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert data["total_estimated_tokens"] == 3 * _TOKENS_PER_SERVER


def test_total_estimated_tokens_one_server(client, tmp_path, monkeypatch):
    settings = _write(tmp_path, "settings.json", {"mcpServers": {"trace": {"command": "python3", "args": []}}})
    _patch(monkeypatch, settings=settings, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert data["total_estimated_tokens"] == _TOKENS_PER_SERVER


def test_total_estimated_tokens_empty(client, tmp_path, monkeypatch):
    settings = _write(tmp_path, "settings.json", {"mcpServers": {}})
    _patch(monkeypatch, settings=settings, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert data["total_estimated_tokens"] == 0


# ---------------------------------------------------------------------------
# Dual-source merge
# ---------------------------------------------------------------------------

def test_merges_servers_from_both_files(client, tmp_path, monkeypatch):
    """Servers from settings.json and desktop config are combined."""
    settings = _write(tmp_path, "settings.json", {
        "mcpServers": {"trace": {"command": "python3", "args": []}},
    })
    desktop = _write(tmp_path, "desktop.json", {
        "mcpServers": {"github": {"command": "npx", "args": ["-y", "github-mcp"]}},
    })
    _patch(monkeypatch, settings=settings, desktop=desktop, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    names = {s["name"] for s in data["servers"]}
    assert names == {"trace", "github"}
    assert data["total_estimated_tokens"] == 2 * _TOKENS_PER_SERVER


def test_desktop_config_only(client, tmp_path, monkeypatch):
    """Works when only the desktop config has servers."""
    desktop = _write(tmp_path, "desktop.json", {
        "mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "fs-mcp"]}},
    })
    _patch(monkeypatch, desktop=desktop, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert len(data["servers"]) == 1
    assert data["servers"][0]["name"] == "filesystem"
    assert data["total_estimated_tokens"] == _TOKENS_PER_SERVER


def test_deduplicates_by_name(client, tmp_path, monkeypatch):
    """Same server name in both files → only one entry in the result."""
    settings = _write(tmp_path, "settings.json", {
        "mcpServers": {"trace": {"command": "python3", "args": ["-m", "server.main"]}},
    })
    desktop = _write(tmp_path, "desktop.json", {
        "mcpServers": {"trace": {"command": "node", "args": ["trace.js"]}},
    })
    _patch(monkeypatch, settings=settings, desktop=desktop, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert len(data["servers"]) == 1
    assert data["total_estimated_tokens"] == _TOKENS_PER_SERVER


def test_settings_wins_on_name_collision(client, tmp_path, monkeypatch):
    """When both files have the same server name, settings.json wins."""
    settings = _write(tmp_path, "settings.json", {
        "mcpServers": {"trace": {"command": "python3", "args": ["-m", "server.main"]}},
    })
    desktop = _write(tmp_path, "desktop.json", {
        "mcpServers": {"trace": {"command": "node", "args": ["trace.js"]}},
    })
    _patch(monkeypatch, settings=settings, desktop=desktop, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    server = data["servers"][0]
    assert server["command"] == "python3"
    assert server["args"] == ["-m", "server.main"]


def test_desktop_config_malformed_still_returns_settings(client, tmp_path, monkeypatch):
    """Malformed desktop config → settings.json servers still returned."""
    settings = _write(tmp_path, "settings.json", _SAMPLE_SETTINGS)
    desktop = tmp_path / "desktop.json"
    desktop.write_text("NOT VALID JSON{{{")
    _patch(monkeypatch, settings=settings, desktop=desktop, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert len(data["servers"]) == 3
    assert data["disclaimer"] == _MCP_DISCLAIMER


def test_settings_malformed_still_returns_desktop(client, tmp_path, monkeypatch):
    """Malformed settings.json → desktop config servers still returned."""
    desktop = _write(tmp_path, "desktop.json", {
        "mcpServers": {"github": {"command": "npx", "args": []}},
    })
    bad = tmp_path / "settings.json"
    bad.write_text("INVALID{{{")
    _patch(monkeypatch, settings=bad, desktop=desktop, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert len(data["servers"]) == 1
    assert data["servers"][0]["name"] == "github"


# ---------------------------------------------------------------------------
# monthly_cost_estimate
# ---------------------------------------------------------------------------

def test_monthly_cost_estimate_is_float(client, tmp_path, monkeypatch):
    settings = _write(tmp_path, "settings.json", _SAMPLE_SETTINGS)
    _patch(monkeypatch, settings=settings, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert isinstance(data["monthly_cost_estimate"], (int, float))


def test_monthly_cost_estimate_zero_when_no_sessions(client, tmp_path, monkeypatch):
    """With no sessions in the last 7 days, monthly cost should be 0."""
    settings = _write(tmp_path, "settings.json", _SAMPLE_SETTINGS)
    _patch(monkeypatch, settings=settings, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert data["monthly_cost_estimate"] == 0.0


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------

def test_api_mcp_handles_malformed_settings(client, tmp_path, monkeypatch):
    bad = tmp_path / "settings.json"
    bad.write_text("NOT VALID JSON{{{")
    _patch(monkeypatch, settings=bad, tmp_path=tmp_path)
    res = client.get("/api/mcp")
    assert res.status_code == 200
    data = res.json()
    assert data["servers"] == []
    assert data["disclaimer"] == _MCP_DISCLAIMER


def test_api_mcp_handles_missing_mcpservers_key(client, tmp_path, monkeypatch):
    """settings.json present but no mcpServers key → empty list."""
    settings = _write(tmp_path, "settings.json", {"other": "data"})
    _patch(monkeypatch, settings=settings, tmp_path=tmp_path)
    data = client.get("/api/mcp").json()
    assert data["servers"] == []
    assert data["total_estimated_tokens"] == 0
