"""Migrate a project-local trace.db to the central ~/.trace/trace.db location."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[1]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.store import TRACE_HOME, TraceStore  # noqa: E402 (after path setup)


def add_cache_columns() -> None:
    """Add cache_creation_tokens and cache_read_tokens columns to sessions table.

    Idempotent – safe to run multiple times.  These columns are now handled
    automatically by TraceStore.init_db() but this function is provided for
    explicit migration of databases created before v0.2.0.
    """
    central_db = TRACE_HOME / "trace.db"
    if not central_db.exists():
        print("No central DB found – nothing to migrate.")
        return

    import sqlite3
    conn = sqlite3.connect(central_db)
    try:
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        added = []
        for col, definition in [
            ("cache_creation_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("cache_read_tokens",     "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {definition}")
                added.append(col)
        conn.commit()
        if added:
            print(f"Added columns to sessions: {', '.join(added)}")
        else:
            print("Cache columns already present – nothing to do.")
    finally:
        conn.close()


def migrate_to_central() -> None:
    """Copy local trace.db → ~/.trace/trace.db if the central DB does not exist yet.

    Idempotent: safe to run multiple times.
    """
    central_db = TRACE_HOME / "trace.db"
    local_db = Path("trace.db")

    if central_db.exists():
        print(f"Central DB already exists at {central_db} – nothing to migrate.")
        return

    if local_db.exists():
        TRACE_HOME.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_db, central_db)
        print(f"Migrated {local_db.resolve()} → {central_db}")
    else:
        print("No local trace.db found – nothing to migrate.")


if __name__ == "__main__":
    add_cache_columns()
    migrate_to_central()
    TraceStore.sync_config(_TRACE_ROOT / "trace_config.yaml")
