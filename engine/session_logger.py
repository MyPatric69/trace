"""Session logger – called by Claude Code's SessionEnd hook.

Reads session metadata from stdin, parses the transcript for token usage,
and logs the session to ~/.trace/trace.db.

Never raises or prints to stdout – all errors go to ~/.trace/session_logger.log.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[1]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.store import TraceStore, TRACE_HOME  # noqa: E402
from engine.transcript_parser import parse_transcript  # noqa: E402 – re-exported for callers

_LOG_FILE = TRACE_HOME / "session_logger.log"

TRACE_HOME.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(_LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
_log = logging.getLogger(__name__)


def _store() -> TraceStore:
    store = TraceStore.default()
    store.init_db()
    return store


def detect_project(cwd: str) -> str | None:
    """Return the registered project name whose path matches *cwd*.

    Lookup order:
    1. Exact path match against ~/.trace/trace.db
    2. Detect project name (git remote origin → directory name) and look
       that name up in the DB
    3. Return None if not registered by either method.
    """
    resolved = str(Path(cwd).resolve())

    try:
        store = _store()

        # 1. Path match
        for project in store.list_projects():
            if str(Path(project["path"]).resolve()) == resolved:
                return project["name"]

        # 2. Name-based fallback
        name = _detect_name(resolved)
        if name and store.get_project(name) is not None:
            return name

    except Exception as exc:
        _log.error("detect_project failed for %s: %s", cwd, exc)

    return None


def _detect_name(project_path: str) -> str | None:
    """Detect project name from git remote origin URL, falling back to dir name."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            url = result.stdout.strip().rstrip("/")
            name = url.split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]
            if name:
                return name
    except Exception:
        pass
    return Path(project_path).resolve().name


def run() -> None:
    """Main entry point – reads JSON from stdin and logs the session."""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception as exc:
        _log.error("Failed to read/parse stdin: %s", exc)
        return

    transcript_path = data.get("transcript_path", "")
    cwd = data.get("cwd", "")
    session_id = data.get("session_id", "")

    usage = parse_transcript(transcript_path)
    input_tokens          = usage["input_tokens"]
    cache_creation_tokens = usage["cache_creation_tokens"]
    cache_read_tokens     = usage["cache_read_tokens"]
    output_tokens         = usage["output_tokens"]
    model                 = usage["model"]
    turns                 = usage["turns"]

    if not input_tokens and not cache_creation_tokens and not output_tokens:
        _log.info("No tokens found for session %s – skipping", session_id)
        return

    project_name = detect_project(cwd)
    if project_name is None:
        _log.info(
            "Project not registered for cwd=%s (session %s) – skipping",
            cwd,
            session_id,
        )
        return

    try:
        store = _store()

        # Delete the live (per-turn) record before inserting the final one
        # so the final accurate record is the only record for this session.
        if session_id:
            try:
                store.delete_live_session(session_id)
            except Exception as exc:
                _log.error("Failed to delete live session %s: %s", session_id, exc)

        store.add_session(
            project_name,
            model,
            input_tokens,
            output_tokens,
            f"Auto-logged via SessionEnd hook – {turns} turns",
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
        )
        _log.info(
            "Logged session %s for project '%s': "
            "%d input, %d cache_creation, %d cache_read, %d output tokens (%s)",
            session_id,
            project_name,
            input_tokens,
            cache_creation_tokens,
            cache_read_tokens,
            output_tokens,
            model,
        )
    except Exception as exc:
        _log.error("Failed to log session %s: %s", session_id, exc)
        return

    # Clear live session file so dashboard shows "No active session"
    try:
        from engine.live_tracker import LiveTracker  # local import avoids circular dependency
        LiveTracker(cwd).clear()
    except Exception as exc:
        _log.error("Failed to clear live session: %s", exc)


if __name__ == "__main__":
    run()
