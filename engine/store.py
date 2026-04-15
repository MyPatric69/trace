import shutil
import sqlite3
from pathlib import Path
from datetime import date, datetime

import yaml

TRACE_HOME = Path.home() / ".trace"


class TraceStore:
    def __init__(self, config_path: str | None = None):
        if config_path is None:
            # Central mode – priority order:
            #   1. ~/.trace/trace_config.yaml  (runtime, if exists)
            #   2. ./trace_config.yaml          (project fallback)
            TRACE_HOME.mkdir(parents=True, exist_ok=True)
            central_config = TRACE_HOME / "trace_config.yaml"
            project_config = Path("trace_config.yaml")

            if central_config.exists():
                resolved = central_config
            elif project_config.exists():
                resolved = project_config
            else:
                raise FileNotFoundError(
                    "No trace_config.yaml found in ~/.trace/ or current directory."
                )

            with open(resolved) as f:
                self.config = yaml.safe_load(f)
            self.config_path = resolved
            self.db_path = TRACE_HOME / "trace.db"

            # Sync project config → ~/.trace/ when falling back to it
            if resolved == project_config:
                self._sync_to_trace_home(project_config)
        else:
            # Explicit config provided (tests / legacy callers)
            resolved = Path(config_path)
            with open(resolved) as f:
                self.config = yaml.safe_load(f)
            self.config_path = resolved
            db_rel = self.config["trace"]["db_path"]
            self.db_path = resolved.parent / db_rel

        self.model_prices = self.config.get("models", {})

    @classmethod
    def default(cls) -> "TraceStore":
        """Standard entry point for all tools – always uses ~/.trace/trace.db."""
        return cls()

    @staticmethod
    def _sync_to_trace_home(source: Path) -> None:
        """Copy source config to ~/.trace/trace_config.yaml; skip if identical."""
        dest = TRACE_HOME / "trace_config.yaml"
        TRACE_HOME.mkdir(parents=True, exist_ok=True)

        source_text = source.read_text()
        if dest.exists():
            if dest.read_text() == source_text:
                return
            action = "updated"
        else:
            action = "created"

        dest.write_text(source_text)

        log = TRACE_HOME / "session_logger.log"
        try:
            with open(log, "a") as f:
                ts = datetime.now().isoformat(timespec="seconds")
                f.write(f"{ts} [config_sync] {action} {dest} from {source}\n")
        except Exception:
            pass

    @classmethod
    def sync_config(cls, source_path: str | Path | None = None) -> None:
        """Explicitly sync a config file to ~/.trace/trace_config.yaml.

        Used by setup_global_template.sh and migrate.py.
        If source_path is None, uses ./trace_config.yaml in cwd.
        """
        source = Path(source_path) if source_path is not None else Path("trace_config.yaml")
        if not source.exists():
            return
        cls._sync_to_trace_home(source)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT    NOT NULL UNIQUE,
                    path        TEXT    NOT NULL,
                    description TEXT,
                    created_at  TEXT    NOT NULL DEFAULT (date('now'))
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id             INTEGER NOT NULL REFERENCES projects(id),
                    date                   TEXT    NOT NULL DEFAULT (date('now')),
                    model                  TEXT    NOT NULL,
                    input_tokens           INTEGER NOT NULL DEFAULT 0,
                    cache_creation_tokens  INTEGER NOT NULL DEFAULT 0,
                    cache_read_tokens      INTEGER NOT NULL DEFAULT 0,
                    output_tokens          INTEGER NOT NULL DEFAULT 0,
                    turns                  INTEGER NOT NULL DEFAULT 0,
                    cost_usd               REAL    NOT NULL DEFAULT 0.0,
                    notes                  TEXT,
                    session_id             TEXT,
                    created_at             TEXT    NOT NULL DEFAULT (datetime('now'))
                );
            """)
            self._migrate_schema(conn)

    @staticmethod
    def _migrate_schema(conn: sqlite3.Connection) -> None:
        """Add new columns / indexes to existing sessions tables (idempotent)."""
        existing = {
            row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        for col, definition in [
            ("cache_creation_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("cache_read_tokens",     "INTEGER NOT NULL DEFAULT 0"),
            ("session_id",            "TEXT"),
            ("turns",                 "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if col not in existing:
                conn.execute(
                    f"ALTER TABLE sessions ADD COLUMN {col} {definition}"
                )
        # Unique index on session_id, excluding NULLs (backward compatible)
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_session_id
               ON sessions(session_id) WHERE session_id IS NOT NULL"""
        )

    def add_project(self, name: str, path: str, description: str = "") -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO projects (name, path, description) VALUES (?, ?, ?)",
                (name, path, description),
            )
            return cursor.lastrowid

    def get_project(self, name: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE name = ?", (name,)
            ).fetchone()
            return dict(row) if row else None

    def list_projects(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def _calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        prices = self.model_prices.get(model) or next(
            (v for k, v in self.model_prices.items() if model.startswith(k)), None
        )
        if not prices:
            return 0.0
        input_cost          = (input_tokens          / 1000) * prices["input_per_1k"]
        cache_creation_cost = (cache_creation_tokens / 1000) * prices.get("cache_creation_per_1k", 0.0)
        cache_read_cost     = (cache_read_tokens     / 1000) * prices.get("cache_read_per_1k",     0.0)
        output_cost         = (output_tokens         / 1000) * prices["output_per_1k"]
        return round(input_cost + cache_creation_cost + cache_read_cost + output_cost, 6)

    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        """Public cost calculator – uses model prices from trace_config.yaml."""
        return self._calculate_cost(
            model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens
        )

    def add_session(
        self,
        project_name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        notes: str = "",
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        turns: int = 0,
    ) -> int:
        """Inserts a session row and returns the new session_id."""
        project = self.get_project(project_name)
        if project is None:
            raise ValueError(f"Project '{project_name}' not found.")

        cost_usd = self._calculate_cost(
            model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens
        )
        today = date.today().isoformat()

        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO sessions
                   (project_id, date, model,
                    input_tokens, cache_creation_tokens, cache_read_tokens,
                    output_tokens, turns, cost_usd, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project["id"], today, model,
                    input_tokens, cache_creation_tokens, cache_read_tokens,
                    output_tokens, turns, cost_usd, notes,
                ),
            )
            return cursor.lastrowid

    def upsert_live_session(
        self,
        session_id: str,
        project_name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        notes: str = "",
        turns: int = 0,
    ) -> int:
        """Insert or update a live session record keyed on *session_id*.

        Called after every Stop hook turn so token data survives hard shutdowns.
        On SessionEnd the live record is deleted and replaced by the final record.
        Returns the sessions table row id.
        """
        project = self.get_project(project_name)
        if project is None:
            raise ValueError(f"Project '{project_name}' not found.")

        cost_usd = self._calculate_cost(
            model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens
        )
        today = date.today().isoformat()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE sessions SET
                           model = ?, input_tokens = ?, cache_creation_tokens = ?,
                           cache_read_tokens = ?, output_tokens = ?, turns = ?,
                           cost_usd = ?, notes = ?
                       WHERE session_id = ?""",
                    (
                        model, input_tokens, cache_creation_tokens,
                        cache_read_tokens, output_tokens, turns,
                        cost_usd, notes, session_id,
                    ),
                )
                return existing["id"]
            else:
                cursor = conn.execute(
                    """INSERT INTO sessions
                           (project_id, date, model,
                            input_tokens, cache_creation_tokens, cache_read_tokens,
                            output_tokens, turns, cost_usd, notes, session_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project["id"], today, model,
                        input_tokens, cache_creation_tokens, cache_read_tokens,
                        output_tokens, turns, cost_usd, notes, session_id,
                    ),
                )
                return cursor.lastrowid

    def delete_live_session(self, session_id: str) -> None:
        """Remove the live record for *session_id* (notes LIKE 'Live – %').

        Called by SessionEnd so the final record is the only record for the
        session.  Safe to call even when no matching row exists.
        """
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE session_id = ? AND notes LIKE 'Live – %'",
                (session_id,),
            )

    def get_sessions(
        self,
        project_name: str | None = None,
        limit: int = 50,
        since_date: str | None = None,
    ) -> list[dict]:
        """Returns sessions, optionally filtered by project and/or date (ISO string)."""
        with self._connect() as conn:
            conditions: list[str] = []
            params: list = []

            if project_name is not None:
                project = self.get_project(project_name)
                if project is None:
                    return []
                conditions.append("project_id = ?")
                params.append(project["id"])

            if since_date is not None:
                conditions.append("date >= ?")
                params.append(since_date)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            params.append(limit)

            rows = conn.execute(
                f"SELECT * FROM sessions {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def get_sessions_with_projects(
        self,
        project_name: str | None = None,
        limit: int = 100,
        since_date: str | None = None,
    ) -> list[dict]:
        """Returns sessions joined with project name, optionally filtered."""
        with self._connect() as conn:
            conditions: list[str] = []
            params: list = []

            if project_name is not None:
                project = self.get_project(project_name)
                if project is None:
                    return []
                conditions.append("s.project_id = ?")
                params.append(project["id"])

            if since_date is not None:
                conditions.append("s.date >= ?")
                params.append(since_date)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            params.append(limit)

            rows = conn.execute(
                f"""SELECT s.*, p.name AS project_name
                    FROM sessions s
                    JOIN projects p ON p.id = s.project_id
                    {where}
                    ORDER BY s.created_at DESC LIMIT ?""",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def get_token_summary(
        self,
        project_name: str | None = None,
        since_date: str | None = None,
        until_date: str | None = None,
    ) -> dict:
        """Returns summed input/output tokens, optionally filtered by project and date."""
        with self._connect() as conn:
            conditions: list[str] = []
            params: list = []

            if project_name is not None:
                project = self.get_project(project_name)
                if project is None:
                    return {
                        "total_input_tokens": 0,
                        "total_cache_creation_tokens": 0,
                        "total_cache_read_tokens": 0,
                        "total_output_tokens": 0,
                    }
                conditions.append("project_id = ?")
                params.append(project["id"])

            if since_date is not None:
                conditions.append("date >= ?")
                params.append(since_date)

            if until_date is not None:
                conditions.append("date <= ?")
                params.append(until_date)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            row = conn.execute(
                f"""SELECT
                       COALESCE(SUM(input_tokens),          0) AS total_input,
                       COALESCE(SUM(cache_creation_tokens), 0) AS total_cache_creation,
                       COALESCE(SUM(cache_read_tokens),     0) AS total_cache_read,
                       COALESCE(SUM(output_tokens),         0) AS total_output,
                       COALESCE(SUM(turns),                 0) AS total_turns
                    FROM sessions {where}""",
                params,
            ).fetchone()
            return {
                "total_input_tokens":          row["total_input"],
                "total_cache_creation_tokens": row["total_cache_creation"],
                "total_cache_read_tokens":     row["total_cache_read"],
                "total_output_tokens":         row["total_output"],
                "total_turns":                 row["total_turns"],
            }

    def get_cost_summary(
        self,
        project_name: str | None = None,
        since_date: str | None = None,
        until_date: str | None = None,
    ) -> dict:
        with self._connect() as conn:
            conditions: list[str] = []
            params: list = []

            if project_name:
                project = self.get_project(project_name)
                if project is None:
                    return {"total_cost_usd": 0.0, "session_count": 0, "avg_cost_per_session": 0.0}
                conditions.append("project_id = ?")
                params.append(project["id"])

            if since_date is not None:
                conditions.append("date >= ?")
                params.append(since_date)

            if until_date is not None:
                conditions.append("date <= ?")
                params.append(until_date)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            row = conn.execute(
                f"""SELECT COALESCE(SUM(cost_usd), 0) AS total_cost,
                           COUNT(*) AS session_count
                    FROM sessions {where}""",
                params,
            ).fetchone()

            total = row["total_cost"]
            count = row["session_count"]
            avg = round(total / count, 6) if count else 0.0
            return {
                "total_cost_usd": round(total, 6),
                "session_count": count,
                "avg_cost_per_session": avg,
            }


if __name__ == "__main__":
    import sys

    if "--sync-config" in sys.argv:
        idx = sys.argv.index("--sync-config")
        src = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        TraceStore.sync_config(src)
    else:
        store = TraceStore()
        store.init_db()
        print("TraceStore initialised successfully.")
        print("DB path:", store.db_path)
