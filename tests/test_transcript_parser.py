"""Tests for engine/transcript_parser.py – parse_transcript peak_context_tokens."""
import json
from pathlib import Path

import pytest

from engine.transcript_parser import parse_transcript


def _write(tmp_path: Path, turns: list[dict]) -> Path:
    p = tmp_path / "session.jsonl"
    with open(p, "w") as f:
        for t in turns:
            f.write(json.dumps(t) + "\n")
    return p


def _turn(req_id: str, input_tokens: int = 0, output_tokens: int = 0,
          cache_creation: int = 0, cache_read: int = 0) -> dict:
    return {
        "type": "assistant",
        "requestId": req_id,
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
                "output_tokens": output_tokens,
            },
        },
    }


def test_peak_context_single_turn(tmp_path):
    p = _write(tmp_path, [_turn("r1", input_tokens=5000, output_tokens=100)])
    result = parse_transcript(str(p))
    assert result["peak_context_tokens"] == 5000


def test_peak_context_is_max_single_turn_not_sum(tmp_path):
    # Three turns: 1k, 10k, 3k → peak = 10k (not 14k sum)
    p = _write(tmp_path, [
        _turn("r1", input_tokens=1000),
        _turn("r2", input_tokens=10000),
        _turn("r3", input_tokens=3000),
    ])
    result = parse_transcript(str(p))
    assert result["peak_context_tokens"] == 10000
    assert result["input_tokens"] == 14000  # cumulative sum unaffected


def test_peak_context_grows_monotonically(tmp_path):
    # Typical session: context grows with each turn
    p = _write(tmp_path, [
        _turn("r1", input_tokens=5000),
        _turn("r2", input_tokens=8000),
        _turn("r3", input_tokens=12000),
    ])
    result = parse_transcript(str(p))
    assert result["peak_context_tokens"] == 12000


def test_peak_context_zero_for_empty_file(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    result = parse_transcript(str(p))
    assert result["peak_context_tokens"] == 0


def test_peak_context_zero_for_missing_file(tmp_path):
    result = parse_transcript(str(tmp_path / "missing.jsonl"))
    assert result["peak_context_tokens"] == 0


def test_peak_context_excludes_cache_creation_from_peak(tmp_path):
    # peak_context_tokens tracks input_tokens only (not cache_creation separately)
    p = _write(tmp_path, [
        _turn("r1", input_tokens=3000, cache_creation=2000),
    ])
    result = parse_transcript(str(p))
    assert result["peak_context_tokens"] == 3000


def test_deduplication_does_not_affect_peak(tmp_path):
    # Duplicate requestId entries – only first counted
    dup = {**_turn("r1", input_tokens=9000)}
    dup2 = {**_turn("r1", input_tokens=9000)}  # same requestId
    p = _write(tmp_path, [dup, dup2])
    result = parse_transcript(str(p))
    assert result["peak_context_tokens"] == 9000
    assert result["turns"] == 1
