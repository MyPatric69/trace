"""Tests for server/tools/session.py – new_session() and get_tips()."""
from pathlib import Path

import pytest
import yaml

from engine.store import TraceStore
import server.tools.session as session_module

# ---------------------------------------------------------------------------
# Shared config / context
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
        "claude-opus-4-5": {"input_per_1k": 0.015, "output_per_1k": 0.075},
        "claude-haiku-4-5": {"input_per_1k": 0.0008, "output_per_1k": 0.004},
    },
}

_WARN_CONFIG = {
    **_MIN_CONFIG,
    "session_health": {
        "warn_tokens": 0,        # triggers warn immediately (even with 0 tokens)
        "critical_tokens": 150000,
        "claude_autocompact_approx": 180000,
    },
}

_TEST_CONTEXT = """\
# AI_CONTEXT.md \u2013 TESTPROJECT

---

## Project

**Name:** TestProject \u2013 A minimal test project
**Status:** Phase 1 complete

---

## Architecture (current)

```
Layer A
    \u2195
Layer B
```

---

## Key decisions

- **Local-heavy** \u2013 all heavy work done locally
- **SQLite** \u2013 no external database
- **FastMCP** \u2013 reduces boilerplate

---

## Next steps

**Phase 1 (complete):**
- [x] Step one done
- [x] Step two done
- [x] Step three done

**Phase 2 (next):**
- [ ] Next step one
- [ ] Next step two

---

## Last updated

2026-01-01
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_env(tmp_path, monkeypatch, config: dict):
    config_path = tmp_path / "trace_config.yaml"
    config_path.write_text(yaml.dump(config), encoding="utf-8")
    (tmp_path / "AI_CONTEXT.md").write_text(_TEST_CONTEXT, encoding="utf-8")

    store = TraceStore(str(config_path))
    store.init_db()
    store.add_project("testproject", str(tmp_path))

    monkeypatch.setattr(session_module, "_store", lambda: store)

    return {"store": store, "tmp_path": tmp_path, "config_path": config_path}


@pytest.fixture
def sess_env(tmp_path, monkeypatch):
    """Normal thresholds – 0 tokens → recommendation='continue'."""
    return _make_env(tmp_path, monkeypatch, _MIN_CONFIG)


@pytest.fixture
def sess_env_warn(tmp_path, monkeypatch):
    """warn_at=0 – even 0 tokens triggers recommendation='warn'."""
    return _make_env(tmp_path, monkeypatch, _WARN_CONFIG)


# ---------------------------------------------------------------------------
# new_session() – structure and early-exit
# ---------------------------------------------------------------------------

def test_new_session_returns_dict(sess_env):
    result = session_module.new_session("testproject")
    assert isinstance(result, dict)


def test_new_session_not_needed_for_fresh_project(sess_env):
    result = session_module.new_session("testproject")
    assert result["status"] == "not_needed"


def test_new_session_not_needed_has_all_keys(sess_env):
    result = session_module.new_session("testproject")
    for key in (
        "status", "project", "recommendation",
        "total_tokens_today", "total_cost_today",
        "handoff_prompt", "message",
    ):
        assert key in result, f"missing key: {key}"


def test_new_session_not_needed_correct_project(sess_env):
    result = session_module.new_session("testproject")
    assert result["project"] == "testproject"


def test_new_session_unknown_project_returns_error(sess_env):
    result = session_module.new_session("no_such_project")
    assert result["status"] == "error"
    assert "not found" in result["message"].lower()


# ---------------------------------------------------------------------------
# new_session() – dry_run
# ---------------------------------------------------------------------------

def test_new_session_dry_run_returns_dry_run_status(sess_env):
    result = session_module.new_session("testproject", dry_run=True)
    assert result["status"] == "dry_run"


def test_new_session_dry_run_returns_handoff_prompt(sess_env):
    result = session_module.new_session("testproject", dry_run=True)
    assert "handoff_prompt" in result
    assert isinstance(result["handoff_prompt"], str)
    assert len(result["handoff_prompt"]) > 0


def test_new_session_dry_run_does_not_write_file(sess_env):
    session_module.new_session("testproject", dry_run=True)
    handoff = sess_env["tmp_path"] / ".trace_handoff.md"
    assert not handoff.exists()


# ---------------------------------------------------------------------------
# new_session() – ok path (warn threshold hit)
# ---------------------------------------------------------------------------

def test_new_session_ok_writes_handoff_file(sess_env_warn):
    result = session_module.new_session("testproject")
    assert result["status"] == "ok"
    handoff = sess_env_warn["tmp_path"] / ".trace_handoff.md"
    assert handoff.exists()
    assert len(handoff.read_text(encoding="utf-8")) > 0


def test_new_session_ok_handoff_matches_compress(sess_env_warn):
    result = session_module.new_session("testproject")
    handoff_file = sess_env_warn["tmp_path"] / ".trace_handoff.md"
    assert handoff_file.read_text(encoding="utf-8") == result["handoff_prompt"]


def test_new_session_ok_logs_session_reset(sess_env_warn):
    store = sess_env_warn["store"]
    before = len(store.get_sessions(project_name="testproject"))
    session_module.new_session("testproject")
    after = store.get_sessions(project_name="testproject")
    assert len(after) == before + 1
    assert after[0]["notes"] == "session_reset"


# ---------------------------------------------------------------------------
# get_tips() – structure
# ---------------------------------------------------------------------------

def test_get_tips_returns_dict(sess_env):
    result = session_module.get_tips("testproject")
    assert isinstance(result, dict)


def test_get_tips_has_all_required_keys(sess_env):
    result = session_module.get_tips("testproject")
    for key in (
        "project", "period", "total_cost",
        "session_count", "tips", "most_expensive_session",
    ):
        assert key in result, f"missing key: {key}"


def test_get_tips_period_is_last_7_days(sess_env):
    result = session_module.get_tips("testproject")
    assert result["period"] == "last_7_days"


def test_get_tips_tips_is_list_of_strings(sess_env):
    result = session_module.get_tips("testproject")
    assert isinstance(result["tips"], list)
    for tip in result["tips"]:
        assert isinstance(tip, str)


def test_get_tips_max_five_tips(sess_env):
    result = session_module.get_tips("testproject")
    assert len(result["tips"]) <= 5


def test_get_tips_most_expensive_session_none_when_empty(sess_env):
    result = session_module.get_tips("testproject")
    assert result["most_expensive_session"] is None


def test_get_tips_project_field(sess_env):
    result = session_module.get_tips("testproject")
    assert result["project"] == "testproject"


def test_get_tips_all_projects_when_no_name(sess_env):
    result = session_module.get_tips()
    assert result["project"] == "all"


# ---------------------------------------------------------------------------
# get_tips() – tip logic
# ---------------------------------------------------------------------------

def test_get_tips_no_sessions_tip_for_empty_project(sess_env):
    result = session_module.get_tips("testproject")
    no_sessions_tip = any("No recent sessions" in t for t in result["tips"])
    assert no_sessions_tip


def test_get_tips_detects_expensive_avg_cost(sess_env):
    store = sess_env["store"]
    # claude-sonnet-4-5: $0.015/1k output → 35k output tokens = $0.525 avg cost
    store.add_session("testproject", "claude-sonnet-4-5", 0, 35000)
    result = session_module.get_tips("testproject")
    expensive_tip = any("avg cost" in t for t in result["tips"])
    assert expensive_tip


def test_get_tips_detects_expensive_model(sess_env):
    store = sess_env["store"]
    store.add_session("testproject", "claude-opus-4-5", 1000, 1000)
    result = session_module.get_tips("testproject")
    model_tip = any("haiku" in t for t in result["tips"])
    assert model_tip


def test_get_tips_most_expensive_session_populated_when_sessions_exist(sess_env):
    store = sess_env["store"]
    store.add_session("testproject", "claude-sonnet-4-5", 1000, 1000)
    result = session_module.get_tips("testproject")
    assert result["most_expensive_session"] is not None
    assert "cost_usd" in result["most_expensive_session"]
