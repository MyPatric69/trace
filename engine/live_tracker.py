"""Live session token tracker.

Called by the PostToolUse hook after every Claude Code tool invocation.
Writes ~/.trace/live_session.json so the dashboard can show current token
usage without waiting for the session to end.

Never raises or prints to stdout – all errors go to ~/.trace/session_logger.log.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[1]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.store import TraceStore, TRACE_HOME  # noqa: E402
from engine.transcript_parser import parse_transcript  # noqa: E402

_LOG_FILE = TRACE_HOME / "session_logger.log"
_LIVE_PATH = TRACE_HOME / "live_session.json"
_STALE_SECONDS = 300  # 5 minutes

logging.basicConfig(
    filename=str(_LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
_log = logging.getLogger(__name__)


def _get_default_store() -> TraceStore | None:
    """Return a ready TraceStore, or None on failure. Monkeypatchable in tests."""
    try:
        store = TraceStore.default()
        store.init_db()
        return store
    except Exception as exc:
        _log.error("live_tracker: failed to get store: %s", exc)
        return None


class LiveTracker:
    def __init__(self, project_path: str | None):
        self.project_name: str | None = None
        self._store: TraceStore | None = None

        if project_path:
            try:
                store = _get_default_store()
                if store is not None:
                    self._store = store
                    resolved = str(Path(project_path).resolve())
                    for proj in store.list_projects():
                        if str(Path(proj["path"]).resolve()) == resolved:
                            self.project_name = proj["name"]
                            break
            except Exception as exc:
                _log.error("LiveTracker.__init__ failed for %s: %s", project_path, exc)

    def update(self, transcript_path: str, cwd: str) -> dict:
        """Parse transcript and write ~/.trace/live_session.json.

        Returns the written dict.
        """
        usage = parse_transcript(transcript_path)
        input_tokens = usage["input_tokens"]
        output_tokens = usage["output_tokens"]
        model = usage["model"]
        turns = usage["turns"]

        # Cost calculation
        cost_usd = 0.0
        try:
            store = self._store or _get_default_store()
            if store is not None:
                cost_usd = store.calculate_cost(model, input_tokens, output_tokens)
        except Exception:
            pass

        # Health based on total token consumption vs config thresholds
        health = "ok"
        try:
            store = self._store or _get_default_store()
            if store is not None:
                session_cfg = store.config.get("session", {})
                warn_at = session_cfg.get("warn_at_tokens", 60_000)
                reset_at = session_cfg.get("recommend_reset_at", 100_000)
                total = input_tokens + output_tokens
                if total >= reset_at:
                    health = "reset"
                elif total >= warn_at:
                    health = "warn"
        except Exception:
            pass

        session_id = Path(transcript_path).stem

        data: dict = {
            "session_id": session_id,
            "project": self.project_name or "unknown",
            "cwd": cwd,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "model": model,
            "turns": turns,
            "health": health,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

        try:
            TRACE_HOME.mkdir(parents=True, exist_ok=True)
            _LIVE_PATH.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            _log.error("LiveTracker.update: failed to write %s: %s", _LIVE_PATH, exc)

        return data

    def clear(self) -> None:
        """Delete ~/.trace/live_session.json. Called when a session ends."""
        try:
            if _LIVE_PATH.exists():
                _LIVE_PATH.unlink()
        except Exception as exc:
            _log.error("LiveTracker.clear: %s", exc)

    def get_live(self) -> dict | None:
        """Return live session data, or None if absent or stale (>5 min)."""
        if not _LIVE_PATH.exists():
            return None
        try:
            age = time.time() - _LIVE_PATH.stat().st_mtime
            if age > _STALE_SECONDS:
                return None
            return json.loads(_LIVE_PATH.read_text())
        except Exception:
            return None
