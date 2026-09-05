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
        "context_window_size":         1_000_000,
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
    assert data["context_window_size"] == 1_000_000
    assert data["cost_usd"] == 0.10
    # Fields not touched by statusline are preserved
    assert data["turns"] == 5
    assert data["project"] == "myproject"
    assert data["input_tokens"] == 1000


def test_statusline_context_window_size_defaults_to_200k_when_absent(client, live_dir, monkeypatch):
    """context_window_size falls back to 200000 when the field is absent from the payload."""
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: None)

    session_id = "no-window-size-001"
    res = client.post("/api/statusline", json={
        "session_id": session_id,
        "cwd":        "/projects/myproject",
        "cost_usd":   0.01,
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["context_window_size"] == 200_000


def test_statusline_updates_context_window_size_on_1m_window_session(client, live_dir, monkeypatch):
    """A Pro/Max session's 1M context window size is written into an existing session file."""
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)

    session_id = "million-window-001"
    existing = {
        "session_id":            session_id,
        "project":               "myproject",
        "cwd":                   "/projects/myproject",
        "input_tokens":          1000,
        "cache_creation_tokens": 500,
        "cache_read_tokens":     200,
        "output_tokens":         300,
        "peak_context_tokens":   418_000,
        "context_window_size":   200_000,
        "context_window_pct":    42.0,
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
        "session_id":          session_id,
        "cwd":                 "/projects/myproject",
        "context_window_pct":  41.8,
        "context_window_size": 1_000_000,
        "cost_usd":            0.06,
        "model":               "claude-sonnet-4-6",
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["context_window_size"] == 1_000_000
    assert data["context_window_pct"] == 41.8


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


def test_statusline_effective_thresholds_capped_for_1m_window(client, live_dir, monkeypatch):
    """A new session created from a 1M-window statusline payload gets warn/critical
    thresholds capped at 20%/40% instead of the raw configured 60%/85%."""
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: None)

    session_id = "million-thresholds-001"
    res = client.post("/api/statusline", json={
        "session_id":          session_id,
        "cwd":                 "/projects/myproject",
        "context_window_pct":  20.0,
        "context_window_size": 1_000_000,
        "cost_usd":            0.02,
        "model":               "claude-sonnet-4-6",
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["effective_warn_context_pct"] == 20.0
    assert data["effective_critical_context_pct"] == 40.0


def test_statusline_effective_thresholds_uncapped_for_200k_window(client, live_dir, monkeypatch):
    """A 200K-window session keeps the raw configured 60%/85% thresholds."""
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: None)

    session_id = "200k-thresholds-001"
    res = client.post("/api/statusline", json={
        "session_id":          session_id,
        "cwd":                 "/projects/myproject",
        "context_window_size": 200_000,
        "model":               "claude-sonnet-4-6",
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["effective_warn_context_pct"] == 60.0
    assert data["effective_critical_context_pct"] == 85.0


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


# ---------------------------------------------------------------------------
# rate_limits, prompt_cache, PR info (new fields from status line)
# ---------------------------------------------------------------------------

def test_statusline_stores_rate_limit_fields_on_new_session(client, live_dir, monkeypatch):
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: None)

    session_id = "rate-limit-001"
    res = client.post("/api/statusline", json={
        "session_id":        session_id,
        "cwd":               "/projects/myproject",
        "rate_limit_5h_pct": 23.0,
        "rate_limit_7d_pct": 12.0,
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["rate_limit_5h_pct"] == 23.0
    assert data["rate_limit_7d_pct"] == 12.0


def test_statusline_stores_rate_limit_fields_on_existing_session(client, live_dir, monkeypatch):
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)

    session_id = "rate-limit-002"
    (live_dir / f"{session_id}.json").write_text(json.dumps({
        "session_id": session_id, "project": "myproject", "cwd": "/projects/myproject",
        "input_tokens": 0, "cache_creation_tokens": 0, "cache_read_tokens": 0,
        "output_tokens": 0, "peak_context_tokens": 0, "context_window_size": 200_000,
        "context_window_pct": 0.0, "cost_usd": 0.0, "model": "claude-sonnet-4-6",
        "turns": 0, "health": "green", "initializing": False, "last_byte_offset": 0,
        "updated_at": "2026-05-04T10:00:00",
    }))

    res = client.post("/api/statusline", json={
        "session_id":        session_id,
        "cwd":               "/projects/myproject",
        "rate_limit_5h_pct": 91.0,
        "rate_limit_7d_pct": 55.0,
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["rate_limit_5h_pct"] == 91.0
    assert data["rate_limit_7d_pct"] == 55.0


def test_statusline_stores_prompt_cache_fields(client, live_dir, monkeypatch):
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: None)

    session_id = "cache-001"
    res = client.post("/api/statusline", json={
        "session_id":      session_id,
        "cwd":             "/projects/myproject",
        "cache_hit_ratio": 0.91,
        "cache_warm":      True,
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["cache_hit_ratio"] == 0.91
    assert data["cache_warm"] is True


def test_statusline_stores_prompt_cache_fields_cold(client, live_dir, monkeypatch):
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)

    session_id = "cache-002"
    (live_dir / f"{session_id}.json").write_text(json.dumps({
        "session_id": session_id, "project": "myproject", "cwd": "/projects/myproject",
        "input_tokens": 0, "cache_creation_tokens": 0, "cache_read_tokens": 0,
        "output_tokens": 0, "peak_context_tokens": 0, "context_window_size": 200_000,
        "context_window_pct": 0.0, "cost_usd": 0.0, "model": "claude-sonnet-4-6",
        "turns": 0, "health": "green", "initializing": False, "last_byte_offset": 0,
        "updated_at": "2026-05-04T10:00:00", "cache_warm": True,
    }))

    res = client.post("/api/statusline", json={
        "session_id":      session_id,
        "cwd":             "/projects/myproject",
        "cache_hit_ratio": 0.40,
        "cache_warm":      False,
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["cache_hit_ratio"] == 0.40
    assert data["cache_warm"] is False  # explicit False must overwrite the prior True


def test_statusline_stores_pr_fields(client, live_dir, monkeypatch):
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: None)

    session_id = "pr-001"
    res = client.post("/api/statusline", json={
        "session_id":      session_id,
        "cwd":             "/projects/myproject",
        "pr_number":       1234,
        "pr_url":          "https://github.com/org/repo/pull/1234",
        "pr_review_state": "pending",
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["pr_number"] == 1234
    assert data["pr_url"] == "https://github.com/org/repo/pull/1234"
    assert data["pr_review_state"] == "pending"


def test_statusline_new_fields_are_null_when_absent(client, live_dir, monkeypatch):
    """rate_limits/prompt_cache/PR fields default to None when the status line
    payload doesn't include them – the dashboard uses this to hide the rows."""
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: None)

    session_id = "no-extra-fields-001"
    res = client.post("/api/statusline", json={
        "session_id": session_id,
        "cwd":        "/projects/myproject",
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["rate_limit_5h_pct"] is None
    assert data["rate_limit_7d_pct"] is None
    assert data["cache_hit_ratio"] is None
    assert data["cache_warm"] is None
    assert data["pr_number"] is None
    assert data["pr_url"] is None
    assert data["pr_review_state"] is None


def test_statusline_existing_session_keeps_new_fields_when_payload_omits_them(client, live_dir, monkeypatch):
    """A later statusline tick without rate_limits/cache/PR data must not erase
    values already recorded for this session (avoids row flicker between ticks)."""
    import engine.live_tracker as lt_module
    monkeypatch.setattr(lt_module, "_LIVE_DIR", live_dir)

    session_id = "keep-fields-001"
    (live_dir / f"{session_id}.json").write_text(json.dumps({
        "session_id": session_id, "project": "myproject", "cwd": "/projects/myproject",
        "input_tokens": 0, "cache_creation_tokens": 0, "cache_read_tokens": 0,
        "output_tokens": 0, "peak_context_tokens": 0, "context_window_size": 200_000,
        "context_window_pct": 0.0, "cost_usd": 0.0, "model": "claude-sonnet-4-6",
        "turns": 0, "health": "green", "initializing": False, "last_byte_offset": 0,
        "updated_at": "2026-05-04T10:00:00",
        "pr_number": 1234, "pr_url": "https://github.com/org/repo/pull/1234",
        "pr_review_state": "approved",
    }))

    res = client.post("/api/statusline", json={
        "session_id": session_id,
        "cwd":        "/projects/myproject",
    })
    assert res.status_code == 200

    data = json.loads((live_dir / f"{session_id}.json").read_text())
    assert data["pr_number"] == 1234
    assert data["pr_review_state"] == "approved"
