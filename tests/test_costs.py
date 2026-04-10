"""Integration tests for server/tools/costs.py – MCP tool layer."""
import pytest

import server.tools.costs as costs_module
from server.tools.costs import log_session, get_costs
from engine.store import TraceStore


@pytest.fixture
def costs_store(tmp_store: TraceStore, monkeypatch):
    """Injects tmp_store into the costs module and pre-registers a test project."""
    monkeypatch.setattr(costs_module, "_store", lambda: tmp_store)
    tmp_store.add_project("alpha", "/projects/alpha", "Test project alpha")
    return tmp_store


# ---------------------------------------------------------------------------
# log_session
# ---------------------------------------------------------------------------

def test_log_session_returns_ok_with_correct_fields(costs_store):
    result = log_session("alpha", "claude-sonnet-4-5", 1000, 500, "test note")

    assert result["status"] == "ok"
    assert isinstance(result["session_id"], int)
    assert result["session_id"] > 0
    assert result["cost_usd"] == pytest.approx(0.0105)
    assert result["project"] == "alpha"
    assert result["model"] == "claude-sonnet-4-5"


def test_log_session_unknown_project_returns_error(costs_store):
    result = log_session("ghost", "claude-sonnet-4-5", 1000, 500)

    assert result["status"] == "error"
    assert "ghost" in result["message"]


def test_log_session_notes_optional(costs_store):
    result = log_session("alpha", "gpt-4o", 2000, 1000)
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# get_costs
# ---------------------------------------------------------------------------

def test_get_costs_for_project_returns_correct_summary(costs_store):
    log_session("alpha", "claude-sonnet-4-5", 1000, 500)   # $0.0105
    log_session("alpha", "gpt-4o", 2000, 1000)             # $0.025

    result = get_costs(project_name="alpha")

    assert result["project"] == "alpha"
    assert result["period"] == "all"
    assert result["session_count"] == 2
    assert result["total_cost_usd"] == pytest.approx(0.0355)
    assert result["avg_cost_per_session"] == pytest.approx(0.0355 / 2)
    assert len(result["sessions"]) == 2


def test_get_costs_no_project_name_returns_all_projects(costs_store: TraceStore):
    # Add a second project directly on the store
    costs_store.add_project("beta", "/projects/beta")
    log_session("alpha", "claude-sonnet-4-5", 1000, 500)   # $0.0105
    # log_session goes through monkeypatched _store, so we use the store directly for beta
    costs_store.add_session("beta", "gpt-4o", 2000, 1000)  # $0.025

    result = get_costs()

    assert result["project"] == "all"
    assert result["session_count"] == 2
    assert result["total_cost_usd"] == pytest.approx(0.0355)


def test_get_costs_period_today_includes_current_sessions(costs_store):
    log_session("alpha", "claude-sonnet-4-5", 1000, 500)

    result = get_costs(project_name="alpha", period="today")

    assert result["period"] == "today"
    assert result["session_count"] == 1
    assert result["total_cost_usd"] == pytest.approx(0.0105)


def test_get_costs_period_future_excludes_all_sessions(costs_store, monkeypatch):
    """Simulate a 'since_date' far in the future to verify filtering works."""
    log_session("alpha", "claude-sonnet-4-5", 1000, 500)

    # Patch _since_date to return a far-future date
    monkeypatch.setattr(costs_module, "_since_date", lambda _: "2099-01-01")

    result = get_costs(project_name="alpha", period="all")

    assert result["session_count"] == 0
    assert result["total_cost_usd"] == 0.0
    assert result["sessions"] == []
