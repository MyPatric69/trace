"""Tests for POST /api/tokenize and GET /api/tokenize/models endpoints."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1]))

from dashboard.server import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# /api/tokenize – structure
# ---------------------------------------------------------------------------

def test_tokenize_returns_correct_structure(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = client.post("/api/tokenize", json={"text": "hello world", "model": "claude-sonnet-4-6"})
    assert res.status_code == 200
    data = res.json()
    for key in ("model", "input_tokens", "cost_estimate_usd", "method", "cost_per_1k_input"):
        assert key in data, f"Missing key: {key}"


def test_tokenize_model_field_echoed(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = client.post("/api/tokenize", json={"text": "hello", "model": "gpt-4o"})
    assert res.json()["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# /api/tokenize – empty / whitespace text
# ---------------------------------------------------------------------------

def test_tokenize_empty_text_returns_zero():
    res = client.post("/api/tokenize", json={"text": "", "model": "claude-sonnet-4-6"})
    assert res.status_code == 200
    data = res.json()
    assert data["input_tokens"] == 0
    assert data["cost_estimate_usd"] == 0.0


def test_tokenize_whitespace_text_returns_zero():
    res = client.post("/api/tokenize", json={"text": "   \n\t  ", "model": "gpt-4o"})
    data = res.json()
    assert data["input_tokens"] == 0
    assert data["cost_estimate_usd"] == 0.0


def test_tokenize_empty_text_no_api_call(monkeypatch):
    """Empty text must never trigger an API call."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-test")
    with patch("urllib.request.urlopen") as mock_open:
        client.post("/api/tokenize", json={"text": "", "model": "claude-sonnet-4-6"})
    mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# /api/tokenize – approximation methods
# ---------------------------------------------------------------------------

def test_tokenize_gpt_uses_word_approximation():
    text = "one two three four"   # 4 words → int(4 * 1.3) = 5
    res = client.post("/api/tokenize", json={"text": text, "model": "gpt-4o"})
    data = res.json()
    assert data["method"] == "approximation"
    assert data["input_tokens"] == int(len(text.split()) * 1.3)


def test_tokenize_unknown_model_uses_char_approximation():
    text = "hello world"
    res = client.post("/api/tokenize", json={"text": text, "model": "some-unknown-model"})
    data = res.json()
    assert data["method"] == "approximation"
    assert data["input_tokens"] == int(len(text) / 3.5)


def test_tokenize_claude_without_api_key_uses_approximation(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    text = "hello world"
    res = client.post("/api/tokenize", json={"text": text, "model": "claude-sonnet-4-6"})
    data = res.json()
    assert data["method"] == "approximation"
    assert data["input_tokens"] == int(len(text) / 3.5)


# ---------------------------------------------------------------------------
# /api/tokenize – API method (mocked)
# ---------------------------------------------------------------------------

def test_tokenize_claude_with_api_key_calls_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-test")
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"input_tokens": 42}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.post("/api/tokenize", json={"text": "hello world", "model": "claude-sonnet-4-6"})
    data = res.json()
    assert data["method"] == "api"
    assert data["input_tokens"] == 42


def test_tokenize_api_failure_falls_back_to_approximation(monkeypatch):
    import urllib.error
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-test")
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        res = client.post("/api/tokenize", json={"text": "hello world", "model": "claude-sonnet-4-6"})
    data = res.json()
    assert data["method"] == "approximation"
    assert data["input_tokens"] > 0


# ---------------------------------------------------------------------------
# /api/tokenize – cost calculation
# ---------------------------------------------------------------------------

def test_tokenize_cost_calculated_from_config():
    # gpt-4o: input_per_1k = 0.0025 in trace_config.yaml
    text = "one two three four five six seven eight"   # 8 words → int(8 * 1.3) = 10
    res = client.post("/api/tokenize", json={"text": text, "model": "gpt-4o"})
    data = res.json()
    assert data["cost_per_1k_input"] == pytest.approx(0.0025)
    expected = (data["input_tokens"] / 1000) * 0.0025
    assert data["cost_estimate_usd"] == pytest.approx(expected, abs=1e-9)


def test_tokenize_unknown_model_cost_is_zero():
    res = client.post("/api/tokenize", json={"text": "hello world", "model": "nonexistent-model"})
    data = res.json()
    assert data["cost_per_1k_input"] == 0.0
    assert data["cost_estimate_usd"] == 0.0


def test_tokenize_cost_rounds_to_six_decimals(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = client.post("/api/tokenize", json={"text": "a b c d e", "model": "claude-sonnet-4-6"})
    data = res.json()
    # cost_estimate_usd must be a float rounded to ≤ 6 decimal places
    assert isinstance(data["cost_estimate_usd"], float)
    assert round(data["cost_estimate_usd"], 6) == data["cost_estimate_usd"]


# ---------------------------------------------------------------------------
# /api/tokenize/models – model list
# ---------------------------------------------------------------------------

def test_tokenize_models_returns_list():
    res = client.get("/api/tokenize/models")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_tokenize_models_list_not_empty():
    data = client.get("/api/tokenize/models").json()
    assert len(data) > 0


def test_tokenize_models_have_required_keys():
    data = client.get("/api/tokenize/models").json()
    for m in data:
        for key in ("id", "input_per_1k", "output_per_1k"):
            assert key in m, f"Model missing key: {key}"
