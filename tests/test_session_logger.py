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
# parse_transcript – token counting
# ---------------------------------------------------------------------------

def test_parse_transcript_returns_correct_tokens(tmp_path):
    transcript = _write_transcript(tmp_path, [
        {"role": "user",      "usage": {"input_tokens": 100, "output_tokens": 0}},
        {"role": "assistant", "model": "claude-sonnet-4-5",
         "usage": {"input_tokens": 80, "output_tokens": 250}},
        {"role": "user",      "usage": {"input_tokens": 60, "output_tokens": 0}},
        {"role": "assistant", "model": "claude-sonnet-4-5",
         "usage": {"input_tokens": 40, "output_tokens": 120}},
    ])
    result = parse_transcript(str(transcript))
    assert result["input_tokens"] == 280
    assert result["output_tokens"] == 370


def test_parse_transcript_returns_correct_turn_count(tmp_path):
    transcript = _write_transcript(tmp_path, [
        {"role": "user",      "usage": {"input_tokens": 50, "output_tokens": 0}},
        {"role": "assistant", "model": "claude-sonnet-4-5",
         "usage": {"input_tokens": 30, "output_tokens": 100}},
    ])
    result = parse_transcript(str(transcript))
    assert result["turns"] == 2


def test_parse_transcript_detects_most_common_model(tmp_path):
    transcript = _write_transcript(tmp_path, [
        {"role": "assistant", "model": "claude-haiku-4-5",
         "usage": {"input_tokens": 10, "output_tokens": 20}},
        {"role": "assistant", "model": "claude-sonnet-4-5",
         "usage": {"input_tokens": 10, "output_tokens": 20}},
        {"role": "assistant", "model": "claude-sonnet-4-5",
         "usage": {"input_tokens": 10, "output_tokens": 20}},
    ])
    result = parse_transcript(str(transcript))
    assert result["model"] == "claude-sonnet-4-5"


def test_parse_transcript_handles_nested_message_usage(tmp_path):
    """Streaming events may nest usage inside a 'message' key."""
    transcript = _write_transcript(tmp_path, [
        {"type": "message_start",
         "message": {"model": "claude-sonnet-4-5",
                     "usage": {"input_tokens": 200, "output_tokens": 0}}},
        {"type": "message_delta",
         "usage": {"output_tokens": 150}},
    ])
    result = parse_transcript(str(transcript))
    assert result["input_tokens"] == 200
    assert result["output_tokens"] == 150


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
    p = tmp_path / "transcript.jsonl"
    p.write_text(
        'not json\n'
        '{"role": "assistant", "model": "claude-sonnet-4-5", '
        '"usage": {"input_tokens": 50, "output_tokens": 100}}\n',
        encoding="utf-8",
    )
    result = parse_transcript(str(p))
    assert result["input_tokens"] == 50
    assert result["output_tokens"] == 100


def test_parse_transcript_unknown_model_when_no_model_field(tmp_path):
    transcript = _write_transcript(tmp_path, [
        {"role": "user", "usage": {"input_tokens": 10, "output_tokens": 0}},
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
        {"role": "assistant", "model": "claude-sonnet-4-5",
         "usage": {"input_tokens": 500, "output_tokens": 200}},
    ], str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_data))

    run()

    sessions = tmp_store.get_sessions("run-project")
    assert len(sessions) == 1
    assert sessions[0]["input_tokens"] == 500
    assert sessions[0]["output_tokens"] == 200
    assert sessions[0]["model"] == "claude-sonnet-4-5"
    assert "Auto-logged" in sessions[0]["notes"]


def test_run_exits_silently_when_project_not_found(tmp_path, tmp_store, monkeypatch):
    monkeypatch.setattr(sl_module, "_store", lambda: tmp_store)

    stdin_data = _make_run_input(tmp_path, [
        {"role": "assistant", "model": "claude-sonnet-4-5",
         "usage": {"input_tokens": 100, "output_tokens": 50}},
    ], str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_data))

    run()  # must not raise

    assert tmp_store.get_sessions() == []


def test_run_exits_silently_when_no_tokens(tmp_path, tmp_store, monkeypatch):
    monkeypatch.setattr(sl_module, "_store", lambda: tmp_store)
    tmp_store.add_project("no-tokens-project", str(tmp_path), "Test")

    stdin_data = _make_run_input(tmp_path, [
        {"role": "user", "content": "Hello"},  # no usage field
    ], str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_data))

    run()  # must not raise

    assert tmp_store.get_sessions("no-tokens-project") == []


def test_run_exits_silently_on_invalid_stdin(tmp_store, monkeypatch):
    monkeypatch.setattr(sl_module, "_store", lambda: tmp_store)
    monkeypatch.setattr(sys, "stdin", io.StringIO("not valid json"))

    run()  # must not raise
