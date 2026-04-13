"""Stop hook handler – updates live token tracking after every completed response.

Claude Code invokes this after each completed response, passing JSON on stdin:
  {
    "session_id": str,
    "transcript_path": str,
    "cwd": str
  }

Never prints to stdout – all errors go to ~/.trace/session_logger.log.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[1]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.store import TRACE_HOME, TraceStore  # noqa: E402
from engine.live_tracker import LiveTracker  # noqa: E402

_LOG_FILE = TRACE_HOME / "session_logger.log"

TRACE_HOME.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(_LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
_log = logging.getLogger(__name__)


def run() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception as exc:
        _log.error("live_session_hook: failed to read stdin: %s", exc)
        return

    transcript_path = data.get("transcript_path", "")
    cwd = data.get("cwd", "")

    if not transcript_path or not cwd:
        return

    try:
        tracker  = LiveTracker(cwd)
        live_data = tracker.update(transcript_path, cwd)
    except Exception as exc:
        _log.error("live_session_hook: update failed: %s", exc)
        return

    # Persist live record to DB after every Stop – survives hard shutdown
    try:
        project_name = tracker.project_name
        if project_name and not live_data.get("initializing"):
            store = TraceStore.default()
            store.init_db()
            turns = live_data.get("turns", 0)
            store.upsert_live_session(
                session_id=live_data["session_id"],
                project_name=project_name,
                model=live_data.get("model", "unknown"),
                input_tokens=int(live_data.get("input_tokens", 0)),
                output_tokens=int(live_data.get("output_tokens", 0)),
                cache_creation_tokens=int(live_data.get("cache_creation_tokens", 0)),
                cache_read_tokens=int(live_data.get("cache_read_tokens", 0)),
                notes=f"Live \u2013 Turn {turns}",
            )
    except Exception as exc:
        _log.error("live_session_hook: upsert_live_session failed: %s", exc)


if __name__ == "__main__":
    run()
