"""Tests for POST /api/statusline endpoint."""
import json
import pytest
import yaml
from fastapi.testclient import TestClient

import dashboard.server as dashboard_module
from dashboard.server import app
from engine.store import TraceStore


_MODEL_PRICES = {
    "claude-sonnet-4-6": {
        "input_per_1k": 0.003,
        "output_per_1k": 0.015,
        "cache_creation_per_1k": 0.00375,
        "cache_read_per_1k": 0.0003,
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
    store.add_project("alpha", "/projects/alpha", "Test project alpha")
    return store


@pytest.fixture
def client(tmp_store, monkeypatch):
    monkeypatch.setattr(dashboard_module, "_store", lambda: tmp_store)
    return TestClient(app)


@pytest.fixture
def live_dir(tmp_path):
    d = tmp_path / "live"
    d.mkdir()
    return d


def test_statusline_updates_existing_session(client, live_dir, monkeypatch):
    """Updates context_window_pct, cost_usd, and updated_at in an existing session file."""
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)

    session_id = "existing-session-001"
    existing = {
        "session_id":            session_id,
        "project":               "myproject",
        "cwd":                   "/projects/myproject",
        "input_tokens":          1000,
        "cache_creation_tokens": 500,
        "cache_read_tokens":     200,
        "output_tokens":         300,
        "peak_context_tokens":   1500,
        "context_window_size":   200_000,
        "context_window_pct":    0.75,
        "cost_usd":              0.05,
        "model":                 "claude-sonnet-4-6",
        "turns":                 5,
        "health":                "green",
        "initializing":          False,
        "last_byte_offset":      12345,
        "updated_at":            "2026-05-04T10:00:00",
    }
    (live_dir / f"{session_id}.json").write_text(json.dumps(existing))

    res = client.post("/api/statusline", json={
        "session_id":                  session_id,
        "cwd":                         "/projects/myproject",
        "context_window_pct":          55.0,
        "input_tokens":                2000,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens":     0,
        "output_tokens":               0,
        "cost_usd":                    0.10,
        "model":                       "claude-sonnet-4-6",
    })
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["context_window_pct"] == 55.0
    assert data["cost_usd"] == 0.10
    # Fields not touched by statusline are preserved
    assert data["turns"] == 5
    assert data["project"] == "myproject"
    assert data["input_tokens"] == 1000


def test_statusline_creates_session_if_missing(client, live_dir, monkeypatch):
    """Creates a new live session file when none exists for the given session_id."""
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: None)

    session_id = "new-session-002"
    res = client.post("/api/statusline", json={
        "session_id":                  session_id,
        "cwd":                         "/projects/brandnew",
        "context_window_pct":          30.0,
        "input_tokens":                500,
        "cache_creation_input_tokens": 100,
        "cache_read_input_tokens":     50,
        "output_tokens":               200,
        "total_input_tokens":          500,
        "total_output_tokens":         200,
        "cost_usd":                    0.02,
        "model":                       "claude-haiku-4-5",
    })
    assert res.status_code == 200

    session_file = live_dir / f"{session_id}.json"
    assert session_file.exists()
    data = json.loads(session_file.read_text())
    assert data["session_id"] == session_id
    assert data["context_window_pct"] == 30.0
    assert data["cost_usd"] == 0.02
    assert data["model"] == "claude-haiku-4-5"
    assert data["peak_context_tokens"] == 650  # 500 + 100 + 50


def test_statusline_returns_200_for_unknown_session_id(client):
    """Returns 200 OK when session_id is empty or missing – never errors."""
    res = client.post("/api/statusline", json={})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res2 = client.post("/api/statusline", json={"session_id": ""})
    assert res2.status_code == 200
    assert res2.json()["status"] == "ok"


def test_statusline_project_detection_from_cwd(client, live_dir, monkeypatch, tmp_store):
    """Project name is resolved from cwd when it matches a registered project path."""
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: tmp_store)

    session_id = "detect-003"
    res = client.post("/api/statusline", json={
        "session_id": session_id,
        "cwd":        "/projects/alpha",
        "cost_usd":   0.01,
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["project"] == "alpha"


def test_statusline_stores_session_duration_ms(client, live_dir, monkeypatch):
    """session_duration_ms and api_duration_ms are stored when creating a new session."""
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: None)

    session_id = "dur-test-001"
    res = client.post("/api/statusline", json={
        "session_id":          session_id,
        "cwd":                 "/projects/myproject",
        "session_duration_ms": 8_100_000,
        "api_duration_ms":     1_380_000,
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["session_duration_ms"] == 8_100_000
    assert data["api_duration_ms"] == 1_380_000


def test_statusline_stores_lines_added_and_removed(client, live_dir, monkeypatch):
    """lines_added and lines_removed are stored in the session file."""
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: None)

    session_id = "lines-test-001"
    res = client.post("/api/statusline", json={
        "session_id":    session_id,
        "cwd":           "/projects/myproject",
        "lines_added":   142,
        "lines_removed": 38,
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["lines_added"] == 142
    assert data["lines_removed"] == 38


def test_statusline_project_dir_fallback(client, live_dir, monkeypatch, tmp_store):
    """project_dir is used as fallback when cwd is empty and no session exists."""
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: tmp_store)

    session_id = "projdir-fallback-001"
    res = client.post("/api/statusline", json={
        "session_id":  session_id,
        "cwd":         "",
        "project_dir": "/projects/alpha",
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["project"] == "alpha"


def _fmt_duration(ms: int):
    """Mirror of the JS fmtDuration helper – used to verify the formatting logic."""
    if not ms:
        return None
    minutes = round(ms / 60_000)
    if minutes >= 60:
        h, m = divmod(minutes, 60)
        return f"{h}h {m}m" if m else f"{h}h"
    return f"{minutes}m"


def test_duration_format_ms_to_human_readable():
    assert _fmt_duration(0) is None
    assert _fmt_duration(60_000) == "1m"
    assert _fmt_duration(30 * 60_000) == "30m"
    assert _fmt_duration(60 * 60_000) == "1h"
    assert _fmt_duration(90 * 60_000) == "1h 30m"
    assert _fmt_duration(135 * 60_000) == "2h 15m"
    assert _fmt_duration(120 * 60_000) == "2h"
