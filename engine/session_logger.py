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
from collections import Counter
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[1]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.store import TraceStore, TRACE_HOME  # noqa: E402

_LOG_FILE = TRACE_HOME / "session_logger.log"

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


def parse_transcript(transcript_path: str) -> dict:
    """Parse a Claude Code transcript.jsonl and return token usage summary.

    Real transcript format (Claude Code ≥ 1.x):
    - Each line has a ``type`` field: "user", "assistant", "attachment", etc.
    - Only ``type: "assistant"`` lines carry token usage.
    - Each assistant line has a ``message`` dict with ``model`` and ``usage``.
    - ``usage`` contains: ``input_tokens``, ``cache_creation_input_tokens``,
      ``cache_read_input_tokens``, ``output_tokens``.
    - Claude Code writes **multiple entries per API request** (same ``requestId``,
      different ``uuid``).  We deduplicate by ``requestId`` to avoid double-counting.

    Input token total = input_tokens + cache_creation_input_tokens + cache_read_input_tokens.
    This reflects all tokens that contributed to the API call, regardless of cache tier.

    Returns:
        dict with keys: input_tokens, output_tokens, model, turns
        All values are 0 / "unknown" if the file is missing or unparseable.
    """
    path = Path(transcript_path)
    if not path.exists():
        return {"input_tokens": 0, "output_tokens": 0, "model": "unknown", "turns": 0}

    input_tokens = 0
    output_tokens = 0
    model_counts: Counter = Counter()
    turns = 0
    seen_request_ids: set = set()

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Only assistant turns carry usage data
                if obj.get("type") != "assistant":
                    continue

                # Deduplicate: Claude Code emits multiple entries per requestId
                request_id = obj.get("requestId")
                if request_id:
                    if request_id in seen_request_ids:
                        continue
                    seen_request_ids.add(request_id)

                turns += 1

                msg = obj.get("message") or {}
                if not isinstance(msg, dict):
                    continue

                # Model
                model_field = msg.get("model")
                if isinstance(model_field, str) and model_field:
                    model_counts[model_field] += 1

                # Usage – sum all input token types (regular + cache creation + cache read)
                usage = msg.get("usage") or {}
                if isinstance(usage, dict):
                    input_tokens += (
                        int(usage.get("input_tokens") or 0)
                        + int(usage.get("cache_creation_input_tokens") or 0)
                        + int(usage.get("cache_read_input_tokens") or 0)
                    )
                    output_tokens += int(usage.get("output_tokens") or 0)

    except Exception as exc:
        _log.error("parse_transcript failed for %s: %s", transcript_path, exc)
        return {"input_tokens": 0, "output_tokens": 0, "model": "unknown", "turns": 0}

    model = model_counts.most_common(1)[0][0] if model_counts else "unknown"
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model": model,
        "turns": turns,
    }


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
    input_tokens = usage["input_tokens"]
    output_tokens = usage["output_tokens"]
    model = usage["model"]
    turns = usage["turns"]

    if not input_tokens and not output_tokens:
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
        store.add_session(
            project_name,
            model,
            input_tokens,
            output_tokens,
            f"Auto-logged via SessionEnd hook – {turns} turns",
        )
        _log.info(
            "Logged session %s for project '%s': %d input, %d output tokens (%s)",
            session_id,
            project_name,
            input_tokens,
            output_tokens,
            model,
        )
    except Exception as exc:
        _log.error("Failed to log session %s: %s", session_id, exc)


if __name__ == "__main__":
    run()
