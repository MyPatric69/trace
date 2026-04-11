"""Tests for engine/session_logger.py."""
import io
import json
import sys
from pathlib import Path

import pytest
import yaml

import engine.session_logger as sl_module
from engine.session_logger import detect_project, parse_transcript, run
from engine.store import TraceStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_transcript(tmp_path: Path, turns: list[dict]) -> Path:
    """Write a list of turn dicts as JSONL to tmp_path/transcript.jsonl."""
    p = tmp_path / "transcript.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for turn in turns:
            f.write(json.dumps(turn) + "\n")
    return p


# ---------------------------------------------------------------------------
# Helpers – real Claude Code transcript format
# ---------------------------------------------------------------------------

def _assistant_turn(
    request_id: str,
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 0,
    cache_creation: int = 0,
    cache_read: int = 0,
    output_tokens: int = 0,
    uuid: str | None = None,
) -> dict:
    """Build an assistant line in the real Claude Code JSONL format."""
    import uuid as _uuid_mod
    return {
        "type": "assistant",
        "requestId": request_id,
        "uuid": uuid or str(_uuid_mod.uuid4()),
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


def _user_turn(content: str = "Hello") -> dict:
    """Build a user line – these carry no usage data."""
    return {"type": "user", "message": {"role": "user", "content": content}}


# ---------------------------------------------------------------------------
# parse_transcript – token counting
# ---------------------------------------------------------------------------

def test_parse_transcript_returns_correct_tokens(tmp_path):
    """input_tokens sums regular + cache_creation + cache_read."""
    transcript = _write_transcript(tmp_path, [
        _user_turn(),
        _assistant_turn("req_1", input_tokens=10, cache_creation=200,
                        cache_read=300, output_tokens=50),
        _user_turn(),
        _assistant_turn("req_2", input_tokens=5, cache_creation=100,
                        cache_read=150, output_tokens=80),
    ])
    result = parse_transcript(str(transcript))
    assert result["input_tokens"] == 10 + 200 + 300 + 5 + 100 + 150  # 765
    assert result["output_tokens"] == 130


def test_parse_transcript_returns_correct_turn_count(tmp_path):
    """turns counts unique assistant requests, not all lines."""
    transcript = _write_transcript(tmp_path, [
        _user_turn(),
        _assistant_turn("req_1", output_tokens=50),
        _user_turn(),
        _assistant_turn("req_2", output_tokens=80),
    ])
    result = parse_transcript(str(transcript))
    assert result["turns"] == 2


def test_parse_transcript_deduplicates_by_request_id(tmp_path):
    """Claude Code writes multiple lines per requestId; only count once."""
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("req_1", input_tokens=10, output_tokens=50, uuid="uuid-a"),
        _assistant_turn("req_1", input_tokens=10, output_tokens=50, uuid="uuid-b"),  # dupe
        _assistant_turn("req_1", input_tokens=10, output_tokens=50, uuid="uuid-c"),  # dupe
        _assistant_turn("req_2", input_tokens=5,  output_tokens=20),
    ])
    result = parse_transcript(str(transcript))
    assert result["input_tokens"] == 15   # req_1(10) + req_2(5), not 35
    assert result["output_tokens"] == 70  # req_1(50) + req_2(20), not 170
    assert result["turns"] == 2


def test_parse_transcript_ignores_non_assistant_lines(tmp_path):
    """user/attachment/system lines are not counted."""
    transcript = _write_transcript(tmp_path, [
        _user_turn("lots of text"),
        {"type": "system", "content": "something"},
        {"type": "attachment", "data": "file"},
        _assistant_turn("req_1", output_tokens=100),
    ])
    result = parse_transcript(str(transcript))
    assert result["turns"] == 1
    assert result["output_tokens"] == 100


def test_parse_transcript_detects_most_common_model(tmp_path):
    transcript = _write_transcript(tmp_path, [
        _assistant_turn("req_1", model="claude-haiku-4-5",   output_tokens=10),
        _assistant_turn("req_2", model="claude-sonnet-4-6",  output_tokens=10),
        _assistant_turn("req_3", model="claude-sonnet-4-6",  output_tokens=10),
    ])
    result = parse_transcript(str(transcript))
    assert result["model"] == "claude-sonnet-4-6"


def test_parse_transcript_missing_file_returns_zeros():
    result = parse_transcript("/nonexistent/path/transcript.jsonl")
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0
    assert result["model"] == "unknown"
    assert result["turns"] == 0


def test_parse_transcript_empty_file_returns_zeros(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    result = parse_transcript(str(p))
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0
    assert result["turns"] == 0


def test_parse_transcript_skips_invalid_json_lines(tmp_path):
    """Invalid JSON lines are skipped; valid assistant lines are counted."""
    import json as _json
    valid_line = _json.dumps(_assistant_turn("req_1", input_tokens=50, output_tokens=100))
    p = tmp_path / "transcript.jsonl"
    p.write_text("not json\n" + valid_line + "\n", encoding="utf-8")
    result = parse_transcript(str(p))
    assert result["input_tokens"] == 50
    assert result["output_tokens"] == 100


def test_parse_transcript_unknown_model_when_no_model_field(tmp_path):
    """Assistant line with no model in message → model returns 'unknown'."""
    transcript = _write_transcript(tmp_path, [
        {"type": "assistant", "requestId": "req_1",
         "message": {"usage": {"input_tokens": 10, "output_tokens": 5}}},
    ])
    result = parse_transcript(str(transcript))
    assert result["model"] == "unknown"


# ---------------------------------------------------------------------------
# detect_project
# ---------------------------------------------------------------------------

def test_detect_project_finds_registered_project_by_path(tmp_path, tmp_store, monkeypatch):
    monkeypatch.setattr(sl_module, "_store", lambda: tmp_store)
    tmp_store.add_project("my-project", str(tmp_path), "Test")

    result = detect_project(str(tmp_path))
    assert result == "my-project"


def test_detect_project_returns_none_for_unregistered_path(tmp_path, tmp_store, monkeypatch):
    monkeypatch.setattr(sl_module, "_store", lambda: tmp_store)

    result = detect_project(str(tmp_path))
    assert result is None


def test_detect_project_resolves_symlinks(tmp_path, tmp_store, monkeypatch):
    """Path stored in DB and cwd must match even if one has trailing slash."""
    monkeypatch.setattr(sl_module, "_store", lambda: tmp_store)
    tmp_store.add_project("sym-project", str(tmp_path) + "/", "Test")

    result = detect_project(str(tmp_path))
    assert result == "sym-project"


def test_detect_project_fallback_finds_by_name(tmp_path, tmp_store, monkeypatch):
    """If path doesn't match, detect_project falls back to name lookup."""
    monkeypatch.setattr(sl_module, "_store", lambda: tmp_store)
    # Register with a DIFFERENT path but same name as the directory
    dir_name = tmp_path.name
    tmp_store.add_project(dir_name, "/some/other/path", "Test")

    # Monkeypatch _detect_name to return the dir name so git lookup isn't needed
    monkeypatch.setattr(sl_module, "_detect_name", lambda p: dir_name)

    result = detect_project(str(tmp_path))
    assert result == dir_name


# ---------------------------------------------------------------------------
# run() – integration
# ---------------------------------------------------------------------------

def _make_run_input(tmp_path: Path, turns: list[dict], cwd: str) -> str:
    transcript = _write_transcript(tmp_path, turns)
    return json.dumps({
        "session_id": "test-session-abc",
        "transcript_path": str(transcript),
        "cwd": cwd,
    })


def test_run_logs_session_when_project_found(tmp_path, tmp_store, monkeypatch):
    monkeypatch.setattr(sl_module, "_store", lambda: tmp_store)
    tmp_store.add_project("run-project", str(tmp_path), "Test")

    stdin_data = _make_run_input(tmp_path, [
        _assistant_turn("req_1", model="claude-sonnet-4-6",
                        input_tokens=50, cache_creation=300, cache_read=150,
                        output_tokens=200),
    ], str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_data))

    run()

    sessions = tmp_store.get_sessions("run-project")
    assert len(sessions) == 1
    assert sessions[0]["input_tokens"] == 500   # 50 + 300 + 150
    assert sessions[0]["output_tokens"] == 200
    assert sessions[0]["model"] == "claude-sonnet-4-6"
    assert "Auto-logged" in sessions[0]["notes"]


def test_run_exits_silently_when_project_not_found(tmp_path, tmp_store, monkeypatch):
    monkeypatch.setattr(sl_module, "_store", lambda: tmp_store)

    stdin_data = _make_run_input(tmp_path, [
        _assistant_turn("req_1", input_tokens=100, output_tokens=50),
    ], str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_data))

    run()  # must not raise

    assert tmp_store.get_sessions() == []


def test_run_exits_silently_when_no_tokens(tmp_path, tmp_store, monkeypatch):
    monkeypatch.setattr(sl_module, "_store", lambda: tmp_store)
    tmp_store.add_project("no-tokens-project", str(tmp_path), "Test")

    stdin_data = _make_run_input(tmp_path, [
        _user_turn("Hello"),  # user lines carry no usage
    ], str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_data))

    run()  # must not raise

    assert tmp_store.get_sessions("no-tokens-project") == []


def test_run_exits_silently_on_invalid_stdin(tmp_store, monkeypatch):
    monkeypatch.setattr(sl_module, "_store", lambda: tmp_store)
    monkeypatch.setattr(sys, "stdin", io.StringIO("not valid json"))

    run()  # must not raise
