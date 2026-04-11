"""Tests for engine/live_tracker.py – LiveTracker."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml

import engine.live_tracker as lt_module
from engine.live_tracker import LiveTracker
from engine.store import TraceStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MODEL_PRICES = {
    "claude-sonnet-4-6": {"input_per_1k": 0.003, "output_per_1k": 0.015},
}

_SESSION_CFG = {
    "warn_at_tokens": 1_000,
    "recommend_reset_at": 2_000,
}


@pytest.fixture
def tmp_store(tmp_path):
    config = {
        "trace": {"db_path": "test.db", "version": "0.1.0"},
        "projects": [],
        "budgets": {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
        "session": _SESSION_CFG,
        "models": _MODEL_PRICES,
    }
    cfg_path = tmp_path / "trace_config.yaml"
    cfg_path.write_text(yaml.dump(config))
    store = TraceStore(str(cfg_path))
    store.init_db()
    return store


@pytest.fixture
def live_path(tmp_path, monkeypatch):
    """Redirect _LIVE_PATH to a temp file so tests don't touch ~/.trace/."""
    path = tmp_path / "live_session.json"
    monkeypatch.setattr(lt_module, "_LIVE_PATH", path)
    return path


@pytest.fixture
def patched_tracker(tmp_store, live_path, monkeypatch):
    """LiveTracker with store monkeypatched and live path redirected."""
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: tmp_store)
    return live_path


def _write_transcript(tmp_path: Path, turns: list[dict]) -> Path:
    p = tmp_path / "transcript.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for turn in turns:
            f.write(json.dumps(turn) + "\n")
    return p


def _assistant_turn(
    request_id: str,
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 0,
    cache_creation: int = 0,
    cache_read: int = 0,
    output_tokens: int = 0,
) -> dict:
    return {
        "type": "assistant",
        "requestId": request_id,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
                "output_tokens": output_tokens,
            },
        },
    }


# ---------------------------------------------------------------------------
# update() – basic write
# ---------------------------------------------------------------------------

def test_update_writes_live_session_json(tmp_path, patched_tracker):
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("req_1", input_tokens=100, output_tokens=50),
    ])
    tracker = LiveTracker(None)
    result = tracker.update(str(transcript), str(tmp_path))

    assert lt_module._LIVE_PATH.exists()
    on_disk = json.loads(lt_module._LIVE_PATH.read_text())
    assert on_disk["input_tokens"] == 100
    assert on_disk["output_tokens"] == 50
    assert on_disk == result


def test_update_returns_correct_token_counts(tmp_path, patched_tracker):
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("req_1", input_tokens=200, cache_creation=300,
                        cache_read=9999, output_tokens=80),
        _assistant_turn("req_2", input_tokens=50, output_tokens=20),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["input_tokens"] == 550   # cache_read excluded
    assert result["output_tokens"] == 100


def test_update_session_id_derived_from_filename(tmp_path, patched_tracker):
    transcript = tmp_path / "abc-1234-session.jsonl"
    transcript.write_text(json.dumps(_assistant_turn("r1", output_tokens=10)) + "\n")
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["session_id"] == "abc-1234-session"


def test_update_sets_updated_at(tmp_path, patched_tracker):
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", output_tokens=5),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert "updated_at" in result
    assert result["updated_at"]  # non-empty


def test_update_calculates_cost(tmp_path, patched_tracker):
    # claude-sonnet-4-6: 1000 in × $0.003 + 500 out × $0.015 = $0.003 + $0.0075 = $0.0105
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=1000, output_tokens=500),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["cost_usd"] == pytest.approx(0.0105)


# ---------------------------------------------------------------------------
# update() – health thresholds
# ---------------------------------------------------------------------------

def test_update_health_ok_below_warn(tmp_path, patched_tracker):
    # warn_at_tokens = 1000, total = 100 + 50 = 150
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=100, output_tokens=50),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["health"] == "ok"


def test_update_health_warn_above_warn_threshold(tmp_path, patched_tracker):
    # warn_at_tokens = 1000, total = 700 + 400 = 1100  → warn
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=700, output_tokens=400),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["health"] == "warn"


def test_update_health_reset_above_reset_threshold(tmp_path, patched_tracker):
    # recommend_reset_at = 2000, total = 1500 + 600 = 2100  → reset
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=1500, output_tokens=600),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["health"] == "reset"


def test_update_health_exactly_at_warn(tmp_path, patched_tracker):
    # exactly at warn_at_tokens = 1000
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=600, output_tokens=400),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["health"] == "warn"


def test_update_health_exactly_at_reset(tmp_path, patched_tracker):
    # exactly at recommend_reset_at = 2000
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=1200, output_tokens=800),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["health"] == "reset"


# ---------------------------------------------------------------------------
# update() – project detection
# ---------------------------------------------------------------------------

def test_update_detects_project_by_path(tmp_path, tmp_store, live_path, monkeypatch):
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: tmp_store)
    tmp_store.add_project("my-project", str(tmp_path), "Test")

    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", output_tokens=10),
    ])
    result = LiveTracker(str(tmp_path)).update(str(transcript), str(tmp_path))
    assert result["project"] == "my-project"


def test_update_project_unknown_when_not_registered(tmp_path, patched_tracker):
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", output_tokens=10),
    ])
    result = LiveTracker(str(tmp_path)).update(str(transcript), str(tmp_path))
    assert result["project"] == "unknown"


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------

def test_clear_removes_live_session_file(tmp_path, live_path):
    live_path.write_text('{"active": true}')
    LiveTracker(None).clear()
    assert not live_path.exists()


def test_clear_noop_when_file_absent(live_path):
    assert not live_path.exists()
    LiveTracker(None).clear()  # must not raise


# ---------------------------------------------------------------------------
# get_live()
# ---------------------------------------------------------------------------

def test_get_live_returns_none_when_file_absent(live_path):
    assert LiveTracker(None).get_live() is None


def test_get_live_returns_data_when_file_exists(tmp_path, live_path):
    payload = {"session_id": "abc", "input_tokens": 42, "health": "ok"}
    live_path.write_text(json.dumps(payload))
    result = LiveTracker(None).get_live()
    assert result is not None
    assert result["input_tokens"] == 42


def test_get_live_returns_none_for_stale_file(tmp_path, live_path, monkeypatch):
    live_path.write_text('{"session_id": "old"}')
    # Pretend file is 6 minutes old (stale_seconds = 300)
    monkeypatch.setattr(lt_module, "_STALE_SECONDS", 0)
    result = LiveTracker(None).get_live()
    assert result is None


def test_get_live_returns_data_within_stale_window(live_path):
    live_path.write_text('{"session_id": "fresh", "turns": 3}')
    result = LiveTracker(None).get_live()
    assert result is not None
    assert result["turns"] == 3
