"""Unit tests for engine/store.py – TraceStore."""
import sqlite3
import pytest

from engine.store import TraceStore


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

def test_init_db_creates_tables(tmp_store: TraceStore):
    with sqlite3.connect(tmp_store.db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "projects" in tables
    assert "sessions" in tables


# ---------------------------------------------------------------------------
# add_project / get_project / list_projects
# ---------------------------------------------------------------------------

def test_add_project_returns_id(tmp_store: TraceStore):
    pid = tmp_store.add_project("alpha", "/projects/alpha")
    assert isinstance(pid, int)
    assert pid > 0


def test_get_project_returns_correct_dict(tmp_store: TraceStore):
    tmp_store.add_project("alpha", "/projects/alpha", "Alpha project")
    project = tmp_store.get_project("alpha")

    assert project is not None
    assert project["name"] == "alpha"
    assert project["path"] == "/projects/alpha"
    assert project["description"] == "Alpha project"
    assert "id" in project
    assert "created_at" in project


def test_get_project_unknown_returns_none(tmp_store: TraceStore):
    assert tmp_store.get_project("does-not-exist") is None


def test_list_projects_returns_all(tmp_store: TraceStore):
    tmp_store.add_project("alpha", "/projects/alpha")
    tmp_store.add_project("beta", "/projects/beta")

    projects = tmp_store.list_projects()
    names = {p["name"] for p in projects}

    assert len(projects) == 2
    assert names == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# add_session
# ---------------------------------------------------------------------------

def test_add_session_returns_int_id(tmp_store: TraceStore):
    tmp_store.add_project("alpha", "/projects/alpha")
    session_id = tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)

    assert isinstance(session_id, int)
    assert session_id > 0


def test_calculate_cost_correct(tmp_store: TraceStore):
    # claude-sonnet-4-5: 1000 in × $0.003 + 500 out × $0.015 = $0.003 + $0.0075 = $0.0105
    assert tmp_store.calculate_cost("claude-sonnet-4-5", 1000, 500) == pytest.approx(0.0105)
    # gpt-4o (fixture): 2000 in × $0.005 + 1000 out × $0.015 = $0.010 + $0.015 = $0.025
    assert tmp_store.calculate_cost("gpt-4o", 2000, 1000) == pytest.approx(0.025)


def test_calculate_cost_with_cache_tokens(tmp_store: TraceStore):
    # claude-sonnet-4-5 fixture prices:
    #   input:          1000 × $0.003 / 1k  = $0.003
    #   cache_creation: 500  × $0.00375 / 1k = $0.001875
    #   cache_read:     200  × $0.0003 / 1k  = $0.00006
    #   output:         400  × $0.015 / 1k   = $0.006
    #   total                                 = $0.010935
    cost = tmp_store.calculate_cost(
        "claude-sonnet-4-5",
        input_tokens=1000,
        output_tokens=400,
        cache_creation_tokens=500,
        cache_read_tokens=200,
    )
    assert cost == pytest.approx(0.010935)


def test_add_session_with_cache_tokens(tmp_store: TraceStore):
    tmp_store.add_project("alpha", "/projects/alpha")
    sid = tmp_store.add_session(
        "alpha", "claude-sonnet-4-5",
        input_tokens=1000, output_tokens=400,
        cache_creation_tokens=500, cache_read_tokens=200,
    )
    assert isinstance(sid, int)
    sessions = tmp_store.get_sessions("alpha")
    assert sessions[0]["cache_creation_tokens"] == 500
    assert sessions[0]["cache_read_tokens"]     == 200


def test_add_session_cache_tokens_included_in_cost(tmp_store: TraceStore):
    tmp_store.add_project("alpha", "/projects/alpha")
    tmp_store.add_session(
        "alpha", "claude-sonnet-4-5",
        input_tokens=1000, output_tokens=400,
        cache_creation_tokens=500, cache_read_tokens=200,
    )
    sessions = tmp_store.get_sessions("alpha")
    assert sessions[0]["cost_usd"] == pytest.approx(0.010935)


def test_get_token_summary_includes_cache_fields(tmp_store: TraceStore):
    tmp_store.add_project("alpha", "/projects/alpha")
    tmp_store.add_session(
        "alpha", "claude-sonnet-4-5",
        input_tokens=1000, output_tokens=500,
        cache_creation_tokens=300, cache_read_tokens=9999,
    )
    summary = tmp_store.get_token_summary("alpha")
    assert summary["total_input_tokens"]          == 1000
    assert summary["total_cache_creation_tokens"] == 300
    assert summary["total_cache_read_tokens"]     == 9999
    assert summary["total_output_tokens"]         == 500


def test_schema_migration_adds_cache_columns(tmp_store: TraceStore):
    import sqlite3
    with sqlite3.connect(tmp_store.db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    assert "cache_creation_tokens" in columns
    assert "cache_read_tokens" in columns


def test_add_session_unknown_project_raises(tmp_store: TraceStore):
    with pytest.raises(ValueError, match="not found"):
        tmp_store.add_session("ghost", "claude-sonnet-4-5", 100, 50)


def test_calculate_cost_unknown_model_returns_zero(tmp_store: TraceStore):
    assert tmp_store.calculate_cost("unknown-model-xyz", 1000, 500) == 0.0


def test_calculate_cost_date_suffixed_model_prefix_match(tmp_store: TraceStore):
    # claude-sonnet-4-5-20250929 should match claude-sonnet-4-5 via prefix
    # claude-sonnet-4-5: 1000 in × $0.003 + 500 out × $0.015 = $0.003 + $0.0075 = $0.0105
    cost = tmp_store.calculate_cost("claude-sonnet-4-5-20250929", 1000, 500)
    assert cost == pytest.approx(0.0105)


def test_calculate_cost_exact_match_still_works(tmp_store: TraceStore):
    # Exact match should still work as before
    cost = tmp_store.calculate_cost("claude-sonnet-4-5", 1000, 500)
    assert cost == pytest.approx(0.0105)


def test_calculate_cost_prefix_match_with_cache_tokens(tmp_store: TraceStore):
    # claude-sonnet-4-5-20250929 should match claude-sonnet-4-5 prefix
    #   input:          1000 × $0.003 / 1k  = $0.003
    #   cache_creation: 500  × $0.00375 / 1k = $0.001875
    #   cache_read:     200  × $0.0003 / 1k  = $0.00006
    #   output:         400  × $0.015 / 1k   = $0.006
    #   total                                 = $0.010935
    cost = tmp_store.calculate_cost(
        "claude-sonnet-4-5-20250929",
        input_tokens=1000,
        output_tokens=400,
        cache_creation_tokens=500,
        cache_read_tokens=200,
    )
    assert cost == pytest.approx(0.010935)


# ---------------------------------------------------------------------------
# get_sessions
# ---------------------------------------------------------------------------

def test_get_sessions_returns_correct_sessions(tmp_store: TraceStore):
    tmp_store.add_project("alpha", "/projects/alpha")
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500, "first")
    tmp_store.add_session("alpha", "gpt-4o", 2000, 1000, "second")

    sessions = tmp_store.get_sessions("alpha")

    assert len(sessions) == 2
    notes = {s["notes"] for s in sessions}
    assert notes == {"first", "second"}


def test_get_sessions_unknown_project_returns_empty(tmp_store: TraceStore):
    assert tmp_store.get_sessions("ghost") == []


def test_get_sessions_since_date_filters_correctly(tmp_store: TraceStore):
    from datetime import date

    tmp_store.add_project("alpha", "/projects/alpha")
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)

    today = date.today().isoformat()
    future = "2099-01-01"

    assert len(tmp_store.get_sessions("alpha", since_date=today)) == 1
    assert tmp_store.get_sessions("alpha", since_date=future) == []


def test_get_sessions_all_projects_when_name_is_none(tmp_store: TraceStore):
    tmp_store.add_project("alpha", "/projects/alpha")
    tmp_store.add_project("beta", "/projects/beta")
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    tmp_store.add_session("beta", "gpt-4o", 2000, 1000)

    all_sessions = tmp_store.get_sessions(project_name=None)
    assert len(all_sessions) == 2


# ---------------------------------------------------------------------------
# get_cost_summary
# ---------------------------------------------------------------------------

def test_get_cost_summary_correct_totals(tmp_store: TraceStore):
    tmp_store.add_project("alpha", "/projects/alpha")
    # session 1: $0.0105  session 2: $0.025  → total $0.0355
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)
    tmp_store.add_session("alpha", "gpt-4o", 2000, 1000)

    summary = tmp_store.get_cost_summary("alpha")

    assert summary["session_count"] == 2
    assert summary["total_cost_usd"] == pytest.approx(0.0355)
    assert summary["avg_cost_per_session"] == pytest.approx(0.0355 / 2)


def test_get_cost_summary_no_sessions_returns_zeros(tmp_store: TraceStore):
    tmp_store.add_project("alpha", "/projects/alpha")
    summary = tmp_store.get_cost_summary("alpha")

    assert summary["total_cost_usd"] == 0.0
    assert summary["session_count"] == 0
    assert summary["avg_cost_per_session"] == 0.0


def test_get_cost_summary_all_projects_when_name_is_none(tmp_store: TraceStore):
    tmp_store.add_project("alpha", "/projects/alpha")
    tmp_store.add_project("beta", "/projects/beta")
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500)   # $0.0105
    tmp_store.add_session("beta", "gpt-4o", 2000, 1000)              # $0.025

    summary = tmp_store.get_cost_summary()
    assert summary["session_count"] == 2
    assert summary["total_cost_usd"] == pytest.approx(0.0355)


def test_get_cost_summary_unknown_project_returns_zeros(tmp_store: TraceStore):
    summary = tmp_store.get_cost_summary("ghost")
    assert summary == {"total_cost_usd": 0.0, "session_count": 0, "avg_cost_per_session": 0.0}


# ---------------------------------------------------------------------------
# until_date parameter
# ---------------------------------------------------------------------------

def test_get_token_summary_until_date_filters_correctly(tmp_store: TraceStore):
    from datetime import date, timedelta

    tmp_store.add_project("alpha", "/projects/alpha")

    # Add sessions with specific dates by manually setting the date in DB
    import sqlite3
    with sqlite3.connect(tmp_store.db_path) as conn:
        project = tmp_store.get_project("alpha")
        pid = project["id"]

        # Session on 2026-04-10
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-10', 'claude-sonnet-4-5', 1000, 500, 0.0105)""",
            (pid,)
        )
        # Session on 2026-04-12
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-12', 'claude-sonnet-4-5', 2000, 1000, 0.021)""",
            (pid,)
        )
        # Session on 2026-04-14
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-14', 'claude-sonnet-4-5', 3000, 1500, 0.0315)""",
            (pid,)
        )

    # Filter: since_date=2026-04-10, until_date=2026-04-12 (should include first 2)
    summary = tmp_store.get_token_summary("alpha", since_date="2026-04-10", until_date="2026-04-12")
    assert summary["total_input_tokens"] == 3000
    assert summary["total_output_tokens"] == 1500


def test_get_token_summary_exact_date_single_day(tmp_store: TraceStore):
    import sqlite3

    tmp_store.add_project("alpha", "/projects/alpha")

    with sqlite3.connect(tmp_store.db_path) as conn:
        project = tmp_store.get_project("alpha")
        pid = project["id"]

        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-13', 'claude-sonnet-4-5', 5000, 2500, 0.0525)""",
            (pid,)
        )
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-14', 'claude-sonnet-4-5', 1000, 500, 0.0105)""",
            (pid,)
        )

    # Exact day: since_date=until_date=2026-04-13
    summary = tmp_store.get_token_summary("alpha", since_date="2026-04-13", until_date="2026-04-13")
    assert summary["total_input_tokens"] == 5000
    assert summary["total_output_tokens"] == 2500


def test_get_cost_summary_until_date_filters_correctly(tmp_store: TraceStore):
    import sqlite3

    tmp_store.add_project("alpha", "/projects/alpha")

    with sqlite3.connect(tmp_store.db_path) as conn:
        project = tmp_store.get_project("alpha")
        pid = project["id"]

        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-10', 'claude-sonnet-4-5', 1000, 500, 0.0105)""",
            (pid,)
        )
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-12', 'claude-sonnet-4-5', 2000, 1000, 0.021)""",
            (pid,)
        )
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-14', 'claude-sonnet-4-5', 3000, 1500, 0.0315)""",
            (pid,)
        )

    # Filter: since_date=2026-04-10, until_date=2026-04-12
    summary = tmp_store.get_cost_summary("alpha", since_date="2026-04-10", until_date="2026-04-12")
    assert summary["session_count"] == 2
    assert summary["total_cost_usd"] == pytest.approx(0.0315)


def test_get_cost_summary_exact_date_single_day(tmp_store: TraceStore):
    import sqlite3

    tmp_store.add_project("alpha", "/projects/alpha")

    with sqlite3.connect(tmp_store.db_path) as conn:
        project = tmp_store.get_project("alpha")
        pid = project["id"]

        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-13', 'claude-sonnet-4-5', 5000, 2500, 0.0525)""",
            (pid,)
        )
        conn.execute(
            """INSERT INTO sessions (project_id, date, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, '2026-04-14', 'claude-sonnet-4-5', 1000, 500, 0.0105)""",
            (pid,)
        )

    # Exact day: since_date=until_date=2026-04-13
    summary = tmp_store.get_cost_summary("alpha", since_date="2026-04-13", until_date="2026-04-13")
    assert summary["session_count"] == 1
    assert summary["total_cost_usd"] == pytest.approx(0.0525)
