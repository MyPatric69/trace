"""Tests for engine/tokenizer_check.py and GET /api/tokenizer_ratio."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))

import engine.tokenizer_check as tc_module
import dashboard.server as srv_module
from dashboard.server import app
from fastapi.testclient import TestClient

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path, cfg: dict) -> Path:
    p = tmp_path / "trace_config.yaml"
    p.write_text(yaml.dump(cfg))
    return p


def _mock_urlopen(token_sequence: list[int]):
    """Return a side_effect that yields token counts in order."""
    it = iter(token_sequence)
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    def _side_effect(req, timeout=10):
        mock_resp.read.return_value = json.dumps({"input_tokens": next(it)}).encode()
        return mock_resp

    return _side_effect


# ---------------------------------------------------------------------------
# engine/tokenizer_check – JSON structure
# ---------------------------------------------------------------------------

def test_run_writes_correct_json_structure(tmp_path, monkeypatch):
    cfg = {
        "models": {
            "claude-opus-4-6":   {"input_per_1k": 0.005, "output_per_1k": 0.025},
            "claude-sonnet-4-6": {"input_per_1k": 0.003, "output_per_1k": 0.015},
        },
        "comparison": {"baseline_model": "claude-sonnet-4-6"},
    }
    _write_config(tmp_path, cfg)
    monkeypatch.setattr(tc_module, "CONFIG_FILE", tmp_path / "trace_config.yaml")
    monkeypatch.setattr(tc_module, "TRACE_HOME",  tmp_path)
    monkeypatch.setattr(tc_module, "RATIO_FILE",  tmp_path / "tokenizer_ratio.json")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    # Place a live session so current_model != baseline_model
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    (live_dir / "s1.json").write_text(json.dumps({"model": "claude-opus-4-6"}))

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen([460, 440])):
        tc_module.run()

    data = json.loads((tmp_path / "tokenizer_ratio.json").read_text())
    for key in ("current_model", "baseline_model", "current_tokens",
                "baseline_tokens", "ratio", "checked_at", "reference_text_hash"):
        assert key in data, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# engine/tokenizer_check – ratio calculation
# ---------------------------------------------------------------------------

def test_run_ratio_calculation(tmp_path, monkeypatch):
    cfg = {
        "models": {
            "claude-opus-4-6":   {"input_per_1k": 0.005, "output_per_1k": 0.025},
            "claude-sonnet-4-6": {"input_per_1k": 0.003, "output_per_1k": 0.015},
        },
        "comparison": {"baseline_model": "claude-sonnet-4-6"},
    }
    _write_config(tmp_path, cfg)
    monkeypatch.setattr(tc_module, "CONFIG_FILE", tmp_path / "trace_config.yaml")
    monkeypatch.setattr(tc_module, "TRACE_HOME",  tmp_path)
    monkeypatch.setattr(tc_module, "RATIO_FILE",  tmp_path / "tokenizer_ratio.json")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    live_dir = tmp_path / "live"
    live_dir.mkdir()
    (live_dir / "s1.json").write_text(json.dumps({"model": "claude-opus-4-6"}))

    # current_model → 550 tokens, baseline_model → 500 tokens
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen([550, 500])):
        tc_module.run()

    data = json.loads((tmp_path / "tokenizer_ratio.json").read_text())
    assert data["current_tokens"]  == 550
    assert data["baseline_tokens"] == 500
    assert data["ratio"] == pytest.approx(550 / 500, abs=1e-4)


def test_run_same_model_skips_api_writes_ratio_one(tmp_path, monkeypatch):
    cfg = {
        "models": {"claude-sonnet-4-6": {"input_per_1k": 0.003, "output_per_1k": 0.015}},
        "comparison": {"baseline_model": "claude-sonnet-4-6"},
    }
    _write_config(tmp_path, cfg)
    monkeypatch.setattr(tc_module, "CONFIG_FILE", tmp_path / "trace_config.yaml")
    monkeypatch.setattr(tc_module, "TRACE_HOME",  tmp_path)
    monkeypatch.setattr(tc_module, "RATIO_FILE",  tmp_path / "tokenizer_ratio.json")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    with patch("urllib.request.urlopen") as mock_open:
        tc_module.run()

    mock_open.assert_not_called()
    data = json.loads((tmp_path / "tokenizer_ratio.json").read_text())
    assert data["ratio"] == 1.0
    assert data["current_tokens"]  == 0
    assert data["baseline_tokens"] == 0


# ---------------------------------------------------------------------------
# GET /api/tokenizer_ratio – endpoint
# ---------------------------------------------------------------------------

def test_api_tokenizer_ratio_returns_file_contents(tmp_path, monkeypatch):
    monkeypatch.setattr(srv_module, "TRACE_HOME", tmp_path)
    payload = {
        "current_model":       "claude-opus-4-6",
        "baseline_model":      "claude-sonnet-4-6",
        "current_tokens":      550,
        "baseline_tokens":     500,
        "ratio":               1.1,
        "checked_at":          "2026-04-27T07:00:00+00:00",
        "reference_text_hash": "abc123",
    }
    (tmp_path / "tokenizer_ratio.json").write_text(json.dumps(payload))

    res = client.get("/api/tokenizer_ratio")
    assert res.status_code == 200
    data = res.json()
    assert data["ratio"] == pytest.approx(1.1)
    assert data["current_model"]  == "claude-opus-4-6"
    assert data["baseline_model"] == "claude-sonnet-4-6"
    assert data["checked_at"]     == "2026-04-27T07:00:00+00:00"


def test_api_tokenizer_ratio_default_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(srv_module, "TRACE_HOME", tmp_path)

    res = client.get("/api/tokenizer_ratio")
    assert res.status_code == 200
    data = res.json()
    assert data["ratio"]      == 1.0
    assert data["checked_at"] is None


# ---------------------------------------------------------------------------
# Dashboard threshold checks (verifying API data drives amber/hidden states)
# ---------------------------------------------------------------------------

def test_api_tokenizer_ratio_above_threshold(tmp_path, monkeypatch):
    """ratio > 1.05 → dashboard should show amber warning."""
    monkeypatch.setattr(srv_module, "TRACE_HOME", tmp_path)
    payload = {
        "current_model": "claude-opus-4-6", "baseline_model": "claude-sonnet-4-6",
        "current_tokens": 560, "baseline_tokens": 500,
        "ratio": 1.12, "checked_at": "2026-04-27T07:00:00+00:00",
        "reference_text_hash": "abc",
    }
    (tmp_path / "tokenizer_ratio.json").write_text(json.dumps(payload))

    data = client.get("/api/tokenizer_ratio").json()
    assert data["ratio"] > 1.05


def test_api_tokenizer_ratio_at_or_below_threshold(tmp_path, monkeypatch):
    """ratio <= 1.05 → dashboard should hide the warning."""
    monkeypatch.setattr(srv_module, "TRACE_HOME", tmp_path)
    payload = {
        "current_model": "claude-sonnet-4-6", "baseline_model": "claude-sonnet-4-5",
        "current_tokens": 510, "baseline_tokens": 500,
        "ratio": 1.02, "checked_at": "2026-04-27T07:00:00+00:00",
        "reference_text_hash": "abc",
    }
    (tmp_path / "tokenizer_ratio.json").write_text(json.dumps(payload))

    data = client.get("/api/tokenizer_ratio").json()
    assert data["ratio"] <= 1.05
