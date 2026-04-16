"""Tests for multi-session live tracking (engine/live_tracker.py + /api/live)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import engine.live_tracker as lt_module
from engine.live_tracker import LiveTracker
from engine.store import TraceStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MODEL_PRICES = {
    "claude-sonnet-4-6": {
        "input_per_1k": 0.003, "output_per_1k": 0.015,
        "cache_creation_per_1k": 0.00375, "cache_read_per_1k": 0.0003,
    },
}

_SESSION_HEALTH_CFG = {
    "warn_tokens": 80_000,
    "critical_tokens": 150_000,
}


@pytest.fixture
def tmp_store(tmp_path):
    config = {
        "trace": {"db_path": "test.db", "version": "0.1.0"},
        "projects": [],
        "budgets": {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
        "session_health": _SESSION_HEALTH_CFG,
        "models": _MODEL_PRICES,
    }
    cfg_path = tmp_path / "trace_config.yaml"
    cfg_path.write_text(yaml.dump(config))
    store = TraceStore(str(cfg_path))
    store.init_db()
    return store


@pytest.fixture
def live_dir(tmp_path, monkeypatch):
    path = tmp_path / "live"
    path.mkdir()
    monkeypatch.setattr(lt_module, "_LIVE_DIR", path)
    return path


@pytest.fixture
def live_path(tmp_path, monkeypatch):
    path = tmp_path / "live_session.json"
    monkeypatch.setattr(lt_module, "_LIVE_PATH", path)
    return path


@pytest.fixture
def last_health_path(tmp_path, monkeypatch):
    path = tmp_path / "last_health.json"
    monkeypatch.setattr(lt_module, "_LAST_HEALTH_PATH", path)
    return path


def _session_file(live_dir: Path, session_id: str, project: str = "proj", turns: int = 1,
                  updated_at: str = "2026-04-16T12:00:00") -> Path:
    data = {
        "session_id": session_id,
        "project": project,
        "turns": turns,
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "cost_usd": 0.001,
        "model": "claude-sonnet-4-6",
        "health": "green",
        "initializing": False,
        "updated_at": updated_at,
    }
    f = live_dir / f"{session_id}.json"
    f.write_text(json.dumps(data))
    return f


# ---------------------------------------------------------------------------
# get_all_active() – returns all live session files
# ---------------------------------------------------------------------------

def test_get_all_active_returns_all_sessions(live_dir, live_path):
    _session_file(live_dir, "sess-a", project="alpha")
    _session_file(live_dir, "sess-b", project="beta")
    sessions = LiveTracker(None).get_all_active()
    assert len(sessions) == 2
    projects = {s["project"] for s in sessions}
    assert projects == {"alpha", "beta"}


def test_get_all_active_returns_empty_when_dir_empty(live_dir, live_path):
    assert LiveTracker(None).get_all_active() == []


def test_get_all_active_returns_empty_when_dir_missing(live_path, monkeypatch, tmp_path):
    monkeypatch.setattr(lt_module, "_LIVE_DIR", tmp_path / "nonexistent")
    assert LiveTracker(None).get_all_active() == []


def test_get_all_active_sorted_by_updated_at_desc(live_dir, live_path):
    _session_file(live_dir, "older", updated_at="2026-04-16T10:00:00")
    _session_file(live_dir, "newer", updated_at="2026-04-16T12:00:00")
    sessions = LiveTracker(None).get_all_active()
    assert sessions[0]["session_id"] == "newer"
    assert sessions[1]["session_id"] == "older"


# ---------------------------------------------------------------------------
# get_all_active() – filters stale sessions (> 10 min old)
# ---------------------------------------------------------------------------

def test_get_all_active_filters_stale_sessions(live_dir, live_path, monkeypatch):
    """Sessions whose file mtime is > _STALE_SECONDS ago are excluded."""
    _session_file(live_dir, "fresh", project="fresh-proj")
    stale_file = _session_file(live_dir, "stale", project="stale-proj")

    # Wind back mtime of the stale file
    old_time = time.time() - (lt_module._STALE_SECONDS + 60)
    import os
    os.utime(stale_file, (old_time, old_time))

    sessions = LiveTracker(None).get_all_active()
    assert len(sessions) == 1
    assert sessions[0]["project"] == "fresh-proj"


def test_get_all_active_all_stale_returns_empty(live_dir, live_path, monkeypatch):
    monkeypatch.setattr(lt_module, "_STALE_SECONDS", 0)
    _session_file(live_dir, "sess-a")
    _session_file(live_dir, "sess-b")
    assert LiveTracker(None).get_all_active() == []


# ---------------------------------------------------------------------------
# clear() – session-id-scoped vs full clear
# ---------------------------------------------------------------------------

def test_clear_with_session_id_removes_only_that_session(live_dir, live_path, last_health_path):
    _session_file(live_dir, "sess-a", project="alpha")
    _session_file(live_dir, "sess-b", project="beta")

    LiveTracker(None).clear(session_id="sess-a")

    assert not (live_dir / "sess-a.json").exists()
    assert (live_dir / "sess-b.json").exists()


def test_clear_without_session_id_removes_all(live_dir, live_path, last_health_path):
    _session_file(live_dir, "sess-a")
    _session_file(live_dir, "sess-b")

    LiveTracker(None).clear()

    assert not (live_dir / "sess-a.json").exists()
    assert not (live_dir / "sess-b.json").exists()


# ---------------------------------------------------------------------------
# Backward compat: migrate live_session.json on first write
# ---------------------------------------------------------------------------

def test_update_migrates_legacy_file_on_first_write(tmp_path, live_dir, last_health_path, monkeypatch, tmp_store):
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: tmp_store)

    # Simulate existing legacy file
    legacy = tmp_path / "live_session.json"
    monkeypatch.setattr(lt_module, "_LIVE_PATH", legacy)
    legacy_data = {
        "session_id": "session-aaa",
        "project": "old-project",
        "input_tokens": 50,
        "output_tokens": 10,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "turns": 1,
        "model": "unknown",
        "health": "green",
        "initializing": False,
        "last_byte_offset": 0,
        "updated_at": "2026-04-16T10:00:00",
    }
    legacy.write_text(json.dumps(legacy_data))

    # New write for a different session
    transcript = tmp_path / "session-bbb.jsonl"
    line = json.dumps({
        "type": "assistant",
        "requestId": "r1",
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 100, "output_tokens": 50,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        },
    })
    transcript.write_text(line + "\n")

    LiveTracker(None).update(str(transcript), str(tmp_path))

    # Legacy file should be deleted
    assert not legacy.exists()
    # New session file should exist in _LIVE_DIR
    assert (live_dir / "session-bbb.json").exists()


def test_load_prev_state_reads_legacy_file_as_fallback(tmp_path, live_dir, monkeypatch):
    """When no per-session file exists, _load_prev_state falls back to _LIVE_PATH."""
    legacy = tmp_path / "live_session.json"
    monkeypatch.setattr(lt_module, "_LIVE_PATH", legacy)
    payload = {"session_id": "sess-x", "input_tokens": 999, "last_byte_offset": 42,
               "output_tokens": 10, "cache_creation_tokens": 0, "cache_read_tokens": 0,
               "turns": 1, "model": "unknown"}
    legacy.write_text(json.dumps(payload))

    result = lt_module._load_prev_state("sess-x")
    assert result is not None
    assert result["input_tokens"] == 999


# ---------------------------------------------------------------------------
# /api/live – multi-session response via TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client(tmp_store, live_dir, live_path, last_health_path, monkeypatch):
    """FastAPI TestClient with all live paths redirected."""
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: tmp_store)

    import dashboard.server as srv_module
    monkeypatch.setattr(srv_module, "_store", lambda: tmp_store)

    from dashboard.server import app
    return TestClient(app)


def test_api_live_returns_all_sessions_when_no_project_filter(app_client, live_dir):
    _session_file(live_dir, "sess-a", project="alpha")
    _session_file(live_dir, "sess-b", project="beta")

    r = app_client.get("/api/live")
    assert r.status_code == 200
    data = r.json()
    assert data["active"] is True
    assert len(data["sessions"]) == 2
    projects = {s["project"] for s in data["sessions"]}
    assert projects == {"alpha", "beta"}


def test_api_live_filters_to_single_session_when_project_set(app_client, live_dir):
    _session_file(live_dir, "sess-a", project="alpha")
    _session_file(live_dir, "sess-b", project="beta")

    r = app_client.get("/api/live?project=alpha")
    assert r.status_code == 200
    data = r.json()
    assert data["active"] is True
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["project"] == "alpha"


def test_api_live_inactive_when_no_sessions(app_client, live_dir):
    r = app_client.get("/api/live")
    data = r.json()
    assert data["active"] is False
    assert data["sessions"] == []


def test_api_live_inactive_when_project_not_matching(app_client, live_dir):
    _session_file(live_dir, "sess-a", project="alpha")

    r = app_client.get("/api/live?project=other")
    data = r.json()
    assert data["active"] is False
    assert data["sessions"] == []
