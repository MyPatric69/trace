"""Migrate a project-local trace.db to the central ~/.trace/trace.db location."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[1]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.store import TRACE_HOME  # noqa: E402 (after path setup)


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
    migrate_to_central()
