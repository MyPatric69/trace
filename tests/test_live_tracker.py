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
    "claude-sonnet-4-6": {
        "input_per_1k": 0.003, "output_per_1k": 0.015,
        "cache_creation_per_1k": 0.00375, "cache_read_per_1k": 0.0003,
    },
}

_SESSION_HEALTH_CFG = {
    "warn_tokens": 1_000,
    "critical_tokens": 2_000,
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
    assert result["input_tokens"]          == 250   # 200 + 50 (regular input only)
    assert result["cache_creation_tokens"] == 300
    assert result["cache_read_tokens"]     == 9999
    assert result["output_tokens"]         == 100


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


def test_update_result_has_cache_token_fields(tmp_path, patched_tracker):
    """update() result always includes cache_creation_tokens and cache_read_tokens."""
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=100, cache_creation=200,
                        cache_read=999, output_tokens=50),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["cache_creation_tokens"] == 200
    assert result["cache_read_tokens"]     == 999
    assert result["input_tokens"]          == 100


def test_update_cost_includes_cache_creation(tmp_path, patched_tracker):
    # claude-sonnet-4-6 fixture prices:
    #   input:          1000 × 0.003 / 1k   = 0.003
    #   cache_creation: 500  × 0.00375 / 1k = 0.001875
    #   cache_read:     0    × 0.0003 / 1k  = 0.0
    #   output:         400  × 0.015 / 1k   = 0.006
    #   total                                = 0.010875
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=1000, cache_creation=500,
                        cache_read=0, output_tokens=400),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["cost_usd"] == pytest.approx(0.010875)


# ---------------------------------------------------------------------------
# update() – health thresholds
# ---------------------------------------------------------------------------

def test_update_health_green_below_warn(tmp_path, patched_tracker):
    # warn_tokens = 1000, total = 100 + 50 = 150  → green
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=100, output_tokens=50),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["health"] == "green"


def test_update_health_yellow_above_warn_threshold(tmp_path, patched_tracker):
    # warn_tokens = 1000, total = 700 + 400 = 1100  → yellow
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=700, output_tokens=400),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["health"] == "yellow"


def test_update_health_red_above_critical_threshold(tmp_path, patched_tracker):
    # critical_tokens = 2000, total = 1500 + 600 = 2100  → red
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=1500, output_tokens=600),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["health"] == "red"


def test_update_health_exactly_at_warn(tmp_path, patched_tracker):
    # exactly at warn_tokens = 1000  → yellow
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=600, output_tokens=400),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["health"] == "yellow"


def test_update_health_exactly_at_critical(tmp_path, patched_tracker):
    # exactly at critical_tokens = 2000  → red
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=1200, output_tokens=800),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["health"] == "red"


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


def test_update_detects_project_from_subdirectory(tmp_path, tmp_store, live_path, monkeypatch):
    """cwd is a subdirectory of the registered project path – should still match."""
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: tmp_store)
    tmp_store.add_project("my-project", str(tmp_path), "Test")

    subdir = tmp_path / "app" / "ui"
    subdir.mkdir(parents=True)

    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", output_tokens=10),
    ])
    # Pass the subdir as cwd (what Claude Code actually sends)
    tracker = LiveTracker(str(subdir))
    assert tracker.project_name == "my-project"
    result = tracker.update(str(transcript), str(subdir))
    assert result["project"] == "my-project"


def test_update_detects_project_by_name_fallback(tmp_path, tmp_store, live_path, monkeypatch):
    """Name-only fallback: different parent dirs but same directory name."""
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: tmp_store)
    # Register under a different base path
    registered_path = tmp_path / "registered" / "my-project"
    registered_path.mkdir(parents=True)
    tmp_store.add_project("my-project", str(registered_path), "Test")

    # cwd has a different parent but same name
    different_base = tmp_path / "other" / "my-project"
    different_base.mkdir(parents=True)

    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", output_tokens=10),
    ])
    tracker = LiveTracker(str(different_base))
    assert tracker.project_name == "my-project"


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
    payload = {"session_id": "abc", "input_tokens": 42, "health": "green"}
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


# ---------------------------------------------------------------------------
# initializing flag – transcript flush race on first PostToolUse
# ---------------------------------------------------------------------------

def test_update_initializing_false_when_tokens_present(tmp_path, patched_tracker):
    """Normal case: transcript has tokens → initializing=False."""
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=100, output_tokens=50),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result["initializing"] is False


def test_update_initializing_true_when_tokens_zero(tmp_path, patched_tracker, monkeypatch):
    """Empty transcript after retry → initializing=True, file still written."""
    slept = []
    monkeypatch.setattr(lt_module.time, "sleep", lambda s: slept.append(s))

    transcript = tmp_path / "session.jsonl"
    transcript.write_text("")  # empty – simulates unflushed file

    result = LiveTracker(None).update(str(transcript), str(tmp_path))

    assert result["initializing"] is True
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0
    assert result["health"] == "green"
    # Retry sleep was called once with 0.5s
    assert slept == [0.5]
    # File was written despite zero tokens
    assert lt_module._LIVE_PATH.exists()


def test_update_retries_once_before_giving_up(tmp_path, patched_tracker, monkeypatch):
    """Only one retry attempt (one sleep call), not a loop."""
    sleep_calls = []
    monkeypatch.setattr(lt_module.time, "sleep", lambda s: sleep_calls.append(s))

    transcript = tmp_path / "session.jsonl"
    transcript.write_text("")

    LiveTracker(None).update(str(transcript), str(tmp_path))

    assert len(sleep_calls) == 1


# ---------------------------------------------------------------------------
# Incremental parsing – Bug 1 fix
# ---------------------------------------------------------------------------

def test_update_stores_last_byte_offset(tmp_path, patched_tracker):
    """After first update(), last_byte_offset is written and > 0."""
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=100, output_tokens=50),
    ])
    result = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert "last_byte_offset" in result
    assert result["last_byte_offset"] > 0


def test_update_incremental_accumulates_tokens(tmp_path, patched_tracker):
    """Second call with appended content adds to totals – no double counting."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps(_assistant_turn("r1", input_tokens=100, output_tokens=50)) + "\n"
    )

    result1 = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result1["input_tokens"] == 100
    assert result1["output_tokens"] == 50
    offset_after_first = result1["last_byte_offset"]
    assert offset_after_first > 0

    # Append a second turn
    with open(transcript, "a") as f:
        f.write(json.dumps(_assistant_turn("r2", input_tokens=200, output_tokens=80)) + "\n")

    result2 = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result2["input_tokens"] == 300   # 100 + 200 – not 200 twice
    assert result2["output_tokens"] == 130  # 50 + 80
    assert result2["turns"] == 2
    assert result2["last_byte_offset"] > offset_after_first


def test_update_incremental_no_double_count_on_repeated_call(tmp_path, patched_tracker):
    """Calling update() twice on an unchanged transcript returns the same totals."""
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=100, output_tokens=50),
    ])
    result1 = LiveTracker(None).update(str(transcript), str(tmp_path))
    result2 = LiveTracker(None).update(str(transcript), str(tmp_path))

    assert result2["input_tokens"] == result1["input_tokens"]
    assert result2["output_tokens"] == result1["output_tokens"]
    assert result2["turns"] == result1["turns"]


def test_update_incremental_new_session_resets(tmp_path, patched_tracker):
    """Different session_id triggers a full re-parse from offset 0."""
    # First session
    transcript_a = tmp_path / "session-aaa.jsonl"
    transcript_a.write_text(
        json.dumps(_assistant_turn("r1", input_tokens=500, output_tokens=100)) + "\n"
    )
    LiveTracker(None).update(str(transcript_a), str(tmp_path))

    # Second session – different file name (different session_id)
    transcript_b = tmp_path / "session-bbb.jsonl"
    transcript_b.write_text(
        json.dumps(_assistant_turn("r1", input_tokens=50, output_tokens=10)) + "\n"
    )
    result = LiveTracker(None).update(str(transcript_b), str(tmp_path))

    # Should see only session B's tokens, not session A's
    assert result["input_tokens"] == 50
    assert result["output_tokens"] == 10
    assert result["session_id"] == "session-bbb"


def test_update_incremental_file_rotation_resets(tmp_path, patched_tracker):
    """If last_byte_offset > file size the file has rotated – restart from 0."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps(_assistant_turn("r1", input_tokens=100, output_tokens=50)) + "\n"
    )
    result1 = LiveTracker(None).update(str(transcript), str(tmp_path))
    assert result1["last_byte_offset"] > 0

    # Simulate file rotation: overwrite with a smaller file
    transcript.write_text(
        json.dumps(_assistant_turn("r2", input_tokens=30, output_tokens=10)) + "\n"
    )
    result2 = LiveTracker(None).update(str(transcript), str(tmp_path))

    # Should see only the new content, not the stale accumulated totals
    assert result2["input_tokens"] == 30
    assert result2["output_tokens"] == 10


def test_update_no_sleep_on_second_call_with_zero_new_tokens(tmp_path, patched_tracker, monkeypatch):
    """No retry sleep on subsequent calls – only on first fresh-session call."""
    sleep_calls = []
    monkeypatch.setattr(lt_module.time, "sleep", lambda s: sleep_calls.append(s))

    transcript = _write_transcript(tmp_path, [
        _assistant_turn("r1", input_tokens=100, output_tokens=50),
    ])
    # First call – has tokens, no retry
    LiveTracker(None).update(str(transcript), str(tmp_path))
    assert sleep_calls == []

    # Second call – same file, same content, no new bytes → no retry
    LiveTracker(None).update(str(transcript), str(tmp_path))
    assert sleep_calls == []
