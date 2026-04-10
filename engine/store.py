import sqlite3
from pathlib import Path
from datetime import date

import yaml


class TraceStore:
    def __init__(self, config_path: str = "trace_config.yaml"):
        config_path = Path(config_path)
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        db_path = self.config["trace"]["db_path"]
        # Resolve db_path relative to the config file's directory
        self.db_path = config_path.parent / db_path
        self.model_prices = self.config.get("models", {})

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
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id    INTEGER NOT NULL REFERENCES projects(id),
                    date          TEXT    NOT NULL DEFAULT (date('now')),
                    model         TEXT    NOT NULL,
                    input_tokens  INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd      REAL    NOT NULL DEFAULT 0.0,
                    notes         TEXT,
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
                );
            """)

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

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        prices = self.model_prices.get(model)
        if not prices:
            return 0.0
        input_cost = (input_tokens / 1000) * prices["input_per_1k"]
        output_cost = (output_tokens / 1000) * prices["output_per_1k"]
        return round(input_cost + output_cost, 6)

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Public cost calculator – uses model prices from trace_config.yaml."""
        return self._calculate_cost(model, input_tokens, output_tokens)

    def add_session(
        self,
        project_name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        notes: str = "",
    ) -> int:
        """Inserts a session row and returns the new session_id."""
        project = self.get_project(project_name)
        if project is None:
            raise ValueError(f"Project '{project_name}' not found.")

        cost_usd = self._calculate_cost(model, input_tokens, output_tokens)
        today = date.today().isoformat()

        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO sessions
                   (project_id, date, model, input_tokens, output_tokens, cost_usd, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project["id"], today, model, input_tokens, output_tokens, cost_usd, notes),
            )
            return cursor.lastrowid

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

    def get_cost_summary(
        self,
        project_name: str | None = None,
        since_date: str | None = None,
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
    store = TraceStore()
    store.init_db()
    print("TraceStore initialised successfully.")
    print("DB path:", store.db_path)
