"""Tests for Per-Turn DB Logging (v0.3.0 Feature 2).

Covers:
  - upsert_live_session() insert + update semantics
  - session_id schema migration
  - SessionEnd cleanup (delete_live_session)
  - No duplicate records after a clean exit
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))

from engine.store import TraceStore
from engine.migrate import add_session_id_column


# ---------------------------------------------------------------------------
# Fixture – isolated store per test
# ---------------------------------------------------------------------------

_MODEL_PRICES = {
    "claude-sonnet-4-6": {
        "input_per_1k": 0.003,
        "output_per_1k": 0.015,
        "cache_creation_per_1k": 0.00375,
        "cache_read_per_1k": 0.0003,
    },
}


@pytest.fixture
def tmp_store(tmp_path):
    config = {
        "trace":    {"db_path": "test.db", "version": "0.3.0"},
        "projects": [],
        "budgets":  {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
        "session_health":  {"warn_tokens": 80_000, "critical_tokens": 150_000},
        "models":   _MODEL_PRICES,
        "api_integration": {"provider": "manual"},
    }
    cfg = tmp_path / "trace_config.yaml"
    cfg.write_text(yaml.dump(config))
    store = TraceStore(str(cfg))
    store.init_db()
    return store


# ---------------------------------------------------------------------------
# upsert_live_session – insert
# ---------------------------------------------------------------------------

def test_upsert_inserts_on_first_call(tmp_store):
    tmp_store.add_project("alpha", "/projects/alpha")
    row_id = tmp_store.upsert_live_session(
        session_id="sess-001",
        project_name="alpha",
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
        notes="Live \u2013 Turn 1",
    )
    assert isinstance(row_id, int)
    sessions = tmp_store.get_sessions("alpha")
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "sess-001"
    assert sessions[0]["input_tokens"] == 100
    assert sessions[0]["output_tokens"] == 50


def test_upsert_records_notes(tmp_store):
    tmp_store.add_project("alpha", "/projects/alpha")
    tmp_store.upsert_live_session(
        "sess-001", "alpha", "claude-sonnet-4-6", 100, 50,
        notes="Live \u2013 Turn 2",
    )
    sessions = tmp_store.get_sessions("alpha")
    assert sessions[0]["notes"] == "Live \u2013 Turn 2"


# ---------------------------------------------------------------------------
# upsert_live_session – update (same session_id)
# ---------------------------------------------------------------------------

def test_upsert_updates_on_second_call(tmp_store):
    tmp_store.add_project("alpha", "/projects/alpha")
    tmp_store.upsert_live_session(
        "sess-001", "alpha", "claude-sonnet-4-6", 100, 50,
        notes="Live \u2013 Turn 1",
    )
    tmp_store.upsert_live_session(
        "sess-001", "alpha", "claude-sonnet-4-6", 200, 100,
        notes="Live \u2013 Turn 2",
    )
    sessions = tmp_store.get_sessions("alpha")
    assert len(sessions) == 1          # not duplicated
    assert sessions[0]["input_tokens"] == 200
    assert sessions[0]["notes"] == "Live \u2013 Turn 2"


def test_upsert_returns_same_id_on_update(tmp_store):
    tmp_store.add_project("alpha", "/projects/alpha")
    sid1 = tmp_store.upsert_live_session(
        "sess-001", "alpha", "claude-sonnet-4-6", 100, 50,
    )
    sid2 = tmp_store.upsert_live_session(
        "sess-001", "alpha", "claude-sonnet-4-6", 200, 100,
    )
    assert sid1 == sid2


def test_upsert_multiple_calls_stay_one_record(tmp_store):
    tmp_store.add_project("alpha", "/projects/alpha")
    for turn in range(1, 6):
        tmp_store.upsert_live_session(
            "sess-001", "alpha", "claude-sonnet-4-6",
            turn * 50, turn * 25,
            notes=f"Live \u2013 Turn {turn}",
        )
    assert len(tmp_store.get_sessions("alpha")) == 1
    assert tmp_store.get_sessions("alpha")[0]["input_tokens"] == 5 * 50


def test_upsert_unknown_project_raises(tmp_store):
    with pytest.raises(ValueError, match="not found"):
        tmp_store.upsert_live_session(
            "sess-001", "nonexistent", "claude-sonnet-4-6", 100, 50,
        )


# ---------------------------------------------------------------------------
# schema – session_id column
# ---------------------------------------------------------------------------

def test_session_id_column_exists_after_init(tmp_store):
    conn = sqlite3.connect(tmp_store.db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    conn.close()
    assert "session_id" in cols


def test_session_id_unique_index_exists(tmp_store):
    conn = sqlite3.connect(tmp_store.db_path)
    indexes = {
        row[1]
        for row in conn.execute("PRAGMA index_list(sessions)").fetchall()
    }
    conn.close()
    assert "idx_sessions_session_id" in indexes


def test_add_session_id_column_migration(tmp_path):
    """add_session_id_column() adds the column to a pre-v0.3.0 DB."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE sessions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        date       TEXT    NOT NULL,
        model      TEXT    NOT NULL,
        notes      TEXT,
        created_at TEXT    NOT NULL DEFAULT (datetime('now'))
    )""")
    conn.commit()
    conn.close()

    add_session_id_column(db)

    conn = sqlite3.connect(db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    conn.close()
    assert "session_id" in cols


def test_add_session_id_column_idempotent(tmp_path):
    """Running migration twice does not raise."""
    db = tmp_path / "db.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_id TEXT, notes TEXT)")
    conn.commit()
    conn.close()

    add_session_id_column(db)
    add_session_id_column(db)   # second call should be silent, not raise


# ---------------------------------------------------------------------------
# delete_live_session
# ---------------------------------------------------------------------------

def test_delete_live_session_removes_record(tmp_store):
    tmp_store.add_project("alpha", "/projects/alpha")
    tmp_store.upsert_live_session(
        "sess-001", "alpha", "claude-sonnet-4-6", 100, 50,
        notes="Live \u2013 Turn 1",
    )
    assert len(tmp_store.get_sessions("alpha")) == 1
    tmp_store.delete_live_session("sess-001")
    assert len(tmp_store.get_sessions("alpha")) == 0


def test_delete_live_session_is_idempotent(tmp_store):
    """delete_live_session() on a nonexistent session_id must not raise."""
    tmp_store.delete_live_session("does-not-exist")


def test_delete_live_session_preserves_final_records(tmp_store):
    """delete_live_session() must not touch final records (session_id=NULL)."""
    tmp_store.add_project("alpha", "/projects/alpha")
    # Final record (no session_id)
    tmp_store.add_session("alpha", "claude-sonnet-4-6", 100, 50, "Final record")
    # Live record
    tmp_store.upsert_live_session(
        "sess-001", "alpha", "claude-sonnet-4-6", 200, 100,
        notes="Live \u2013 Turn 1",
    )
    assert len(tmp_store.get_sessions("alpha")) == 2
    tmp_store.delete_live_session("sess-001")
    sessions = tmp_store.get_sessions("alpha")
    assert len(sessions) == 1
    assert sessions[0]["session_id"] is None
    assert sessions[0]["notes"] == "Final record"


# ---------------------------------------------------------------------------
# Clean-exit scenario: Stop hook × N → SessionEnd → no duplicates
# ---------------------------------------------------------------------------

def test_no_duplicate_after_clean_exit(tmp_store):
    """Simulate 3 Stop turns + SessionEnd: only one final record remains."""
    tmp_store.add_project("alpha", "/projects/alpha")
    session_id = "sess-clean-exit"

    # Stop hook fires 3 times (upsert each turn)
    for turn in range(1, 4):
        tmp_store.upsert_live_session(
            session_id, "alpha", "claude-sonnet-4-6",
            turn * 100, turn * 50,
            notes=f"Live \u2013 Turn {turn}",
        )

    # SessionEnd: delete live record, insert final
    tmp_store.delete_live_session(session_id)
    tmp_store.add_session(
        "alpha", "claude-sonnet-4-6", 300, 150,
        "Auto-logged via SessionEnd hook \u2013 3 turns",
    )

    sessions = tmp_store.get_sessions("alpha")
    assert len(sessions) == 1
    assert sessions[0]["session_id"] is None
    assert sessions[0]["input_tokens"] == 300
    assert "SessionEnd" in sessions[0]["notes"]


def test_two_independent_sessions_no_crosstalk(tmp_store):
    """Upserting two different session_ids creates two separate records."""
    tmp_store.add_project("alpha", "/projects/alpha")
    tmp_store.upsert_live_session(
        "sess-A", "alpha", "claude-sonnet-4-6", 100, 50,
        notes="Live \u2013 Turn 1",
    )
    tmp_store.upsert_live_session(
        "sess-B", "alpha", "claude-sonnet-4-6", 200, 100,
        notes="Live \u2013 Turn 1",
    )
    sessions = tmp_store.get_sessions("alpha")
    assert len(sessions) == 2
    ids = {s["session_id"] for s in sessions}
    assert ids == {"sess-A", "sess-B"}
