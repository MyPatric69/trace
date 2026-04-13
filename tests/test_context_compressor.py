"""Tests for engine/context_compressor.py."""
from pathlib import Path

import pytest
import yaml

from engine.context_compressor import ContextCompressor

REPO_ROOT = Path(__file__).parents[1]

# ---------------------------------------------------------------------------
# Fixtures / shared data
# ---------------------------------------------------------------------------

_MIN_CONFIG = {
    "trace": {"db_path": "trace.db", "version": "0.1.0"},
    "projects": [],
    "budgets": {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
    "session_health": {
        "warn_tokens": 80000,
        "critical_tokens": 150000,
        "claude_autocompact_approx": 180000,
    },
    "models": {
        "claude-sonnet-4-5": {"input_per_1k": 0.003, "output_per_1k": 0.015},
    },
}

# Deliberately verbose so compress() always produces a shorter result.
_TEST_CONTEXT = """\
# AI_CONTEXT.md – TEST PROJECT

> Re-entry point for AI assistants working on TEST PROJECT.
> Keep it current. It replaces reading multiple separate docs.

---

## Project

**Name:** TestProject \u2013 A test project for unit testing
**Type:** MCP Server (Python / FastMCP)
**License:** MIT
**Repo:** github.com/example/test
**Status:** Phase 1 complete

---

## What TestProject does

TestProject is a test MCP server used only in unit tests.
It provides no real capabilities beyond verifying that the
ContextCompressor class works correctly under all conditions.

---

## Architecture (current)

```
Layer A (top)
    \u2195 protocol
Layer B (middle)
    \u2195 internal
Layer C (bottom)
```

---

## Key decisions

- **Local-heavy** \u2013 all processing done locally, zero API cost
- **SQLite** \u2013 no external database dependencies required
- **FastMCP** \u2013 reduces boilerplate, Pythonic, well-maintained

---

## Next steps

**Phase 1 (complete):**
- [x] Step one: scaffold project structure
- [x] Step two: implement core store
- [x] Step three: add MCP tools
- [x] Step four: write integration tests

**Phase 2 (next):**
- [ ] Next step one: add git watcher
- [ ] Next step two: add doc synthesizer
- [ ] Next step three: add context compressor
- [ ] Next step four: add session reset tool

---

## Last updated

2026-01-01
"""


@pytest.fixture
def compressor(tmp_path):
    config_path = tmp_path / "trace_config.yaml"
    config_path.write_text(yaml.dump(_MIN_CONFIG), encoding="utf-8")
    (tmp_path / "AI_CONTEXT.md").write_text(_TEST_CONTEXT, encoding="utf-8")
    return ContextCompressor(str(tmp_path), config_path=str(config_path))


@pytest.fixture
def real_compressor():
    """Compressor pointing at the real TRACE repo and its config."""
    return ContextCompressor(str(REPO_ROOT), config_path=str(REPO_ROOT / "trace_config.yaml"))


# ---------------------------------------------------------------------------
# compress()
# ---------------------------------------------------------------------------

def test_compress_returns_non_empty_string(compressor):
    result = compressor.compress()
    assert isinstance(result, str)
    assert len(result) > 0


def test_compress_output_shorter_than_input(compressor):
    input_text = (compressor.project_path / "AI_CONTEXT.md").read_text(encoding="utf-8")
    result = compressor.compress()
    assert len(result) < len(input_text)


def test_compress_real_repo_shorter_than_input(real_compressor):
    input_text = (real_compressor.project_path / "AI_CONTEXT.md").read_text(encoding="utf-8")
    result = real_compressor.compress()
    assert len(result) < len(input_text)


def test_compress_contains_project_name(compressor):
    result = compressor.compress()
    assert "TestProject" in result


def test_compress_contains_status(compressor):
    result = compressor.compress()
    assert "Phase 1 complete" in result


def test_compress_contains_next_steps(compressor):
    result = compressor.compress()
    assert "Next step one" in result


def test_compress_contains_completed_items(compressor):
    result = compressor.compress()
    assert "[x]" in result


def test_compress_limits_completed_to_last_three(compressor):
    result = compressor.compress()
    # Step one is the 1st of 4 completed; only last 3 are kept
    assert "Step one" not in result
    assert "Step two" in result
    assert "Step three" in result
    assert "Step four" in result


def test_compress_limits_upcoming_to_three(compressor):
    result = compressor.compress()
    assert "Next step one" in result
    assert "Next step two" in result
    assert "Next step three" in result
    assert "Next step four" not in result


def test_compress_contains_key_decisions(compressor):
    result = compressor.compress()
    assert "Local-heavy" in result


def test_compress_contains_last_updated(compressor):
    result = compressor.compress()
    assert "2026-01-01" in result


def test_compress_respects_max_tokens(compressor):
    result = compressor.compress(max_tokens=50)
    # Allow a small buffer for the truncation marker
    assert compressor.estimate_tokens(result) <= 100


def test_compress_graceful_when_no_context_file(tmp_path):
    config_path = tmp_path / "trace_config.yaml"
    config_path.write_text(yaml.dump(_MIN_CONFIG), encoding="utf-8")
    # Deliberately no AI_CONTEXT.md written
    cc = ContextCompressor(str(tmp_path), config_path=str(config_path))
    result = cc.compress()
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# estimate_tokens()
# ---------------------------------------------------------------------------

def test_estimate_tokens_returns_int(compressor):
    result = compressor.estimate_tokens("hello world this is a test")
    assert isinstance(result, int)


def test_estimate_tokens_reasonable_value(compressor):
    # 100 words → expect roughly 130 tokens (× 1.3)
    text = " ".join(["word"] * 100)
    result = compressor.estimate_tokens(text)
    assert 100 <= result <= 200


def test_estimate_tokens_empty_string(compressor):
    assert compressor.estimate_tokens("") == 0


def test_estimate_tokens_scales_with_length(compressor):
    short = compressor.estimate_tokens("hello world")
    long = compressor.estimate_tokens("hello world " * 10)
    assert long > short


# ---------------------------------------------------------------------------
# get_session_recommendation()
# ---------------------------------------------------------------------------

def test_get_session_recommendation_returns_dict(compressor):
    result = compressor.get_session_recommendation()
    assert isinstance(result, dict)


def test_get_session_recommendation_has_required_keys(compressor):
    result = compressor.get_session_recommendation()
    for key in ("total_tokens_today", "total_cost_today", "recommendation", "message"):
        assert key in result


def test_get_session_recommendation_continue_for_zero_tokens(compressor):
    # No sessions in DB → 0 tokens → "continue"
    result = compressor.get_session_recommendation()
    assert result["recommendation"] == "continue"
    assert result["total_tokens_today"] == 0


def test_get_session_recommendation_no_compressed_context_when_continue(compressor):
    result = compressor.get_session_recommendation()
    assert result["recommendation"] == "continue"
    assert "compressed_context" not in result


def test_get_session_recommendation_warn_includes_compressed_context(compressor, monkeypatch):
    monkeypatch.setattr(compressor, "warn_at", 0)
    monkeypatch.setattr(compressor, "reset_at", 50_000)
    result = compressor.get_session_recommendation()
    assert result["recommendation"] == "warn"
    assert "compressed_context" in result
    assert isinstance(result["compressed_context"], str)
    assert len(result["compressed_context"]) > 0


def test_get_session_recommendation_reset_includes_compressed_context(compressor, monkeypatch):
    monkeypatch.setattr(compressor, "warn_at", 0)
    monkeypatch.setattr(compressor, "reset_at", 0)
    result = compressor.get_session_recommendation()
    assert result["recommendation"] == "reset"
    assert "compressed_context" in result


def test_get_session_recommendation_total_cost_is_float(compressor):
    result = compressor.get_session_recommendation()
    assert isinstance(result["total_cost_today"], float)
