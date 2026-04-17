"""Live session token tracker.

Called by the PostToolUse hook after every Claude Code tool invocation.
Writes ~/.trace/live_session.json so the dashboard can show current token
usage without waiting for the session to end.

Performance: incremental parsing.  On each call we seek to the last known
byte offset and process only new lines.  For a long session this reduces
parse time from O(whole file) to O(new bytes since last call) – typically
a few hundred bytes, well under 50 ms.

Never raises or prints to stdout – all errors go to ~/.trace/session_logger.log.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[1]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.store import TraceStore, TRACE_HOME  # noqa: E402

_LOG_FILE = TRACE_HOME / "session_logger.log"
_LIVE_DIR  = TRACE_HOME / "live"          # per-session files: {session_id}.json
_LIVE_PATH = TRACE_HOME / "live_session.json"  # legacy – migrated on first write
_LAST_HEALTH_PATH = TRACE_HOME / "last_health.json"
_STALE_SECONDS = 600  # 10 minutes
_SANITY_LIMIT = 200_000

# Severity order for health colours – used to detect escalations
_HEALTH_ORD: dict[str, int] = {"green": 0, "yellow": 1, "red": 2}
# Maps internal colour names to the status strings used by notifier / last_health
_HEALTH_STATUS: dict[str, str] = {"green": "ok", "yellow": "warn", "red": "reset"}

TRACE_HOME.mkdir(parents=True, exist_ok=True)
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


def _load_prev_state(session_id: str) -> dict | None:
    """Load previous state for session_id from the per-session dir, or the legacy file."""
    new_path = _LIVE_DIR / f"{session_id}.json"
    if new_path.exists():
        try:
            data = json.loads(new_path.read_text())
            if data.get("session_id") == session_id:
                return data
        except Exception:
            pass
    if _LIVE_PATH.exists():
        try:
            data = json.loads(_LIVE_PATH.read_text())
            if data.get("session_id") == session_id:
                return data
        except Exception:
            pass
    return None


def _incremental_parse(transcript_path: str, prev: dict | None) -> dict:
    """Parse only new bytes in the transcript since the last known offset.

    Carry-forwards accumulated totals from *prev* (same session).  Falls back
    to a full parse from offset 0 when *prev* is None or the file has rotated.

    Token counting rules (same as transcript_parser.py):
    - Only ``type:"assistant"`` lines carry usage.
    - Deduplicate by ``requestId`` within each chunk.
    - Include  ``input_tokens + cache_creation_input_tokens``
    - Exclude  ``cache_read_input_tokens``  (re-counts cached context every call)
    """
    path = Path(transcript_path)

    # Carry forward accumulated state
    acc_input:          int = int(prev["input_tokens"])                       if prev else 0
    acc_cache_creation: int = int(prev.get("cache_creation_tokens", 0))       if prev else 0
    acc_cache_read:     int = int(prev.get("cache_read_tokens", 0))            if prev else 0
    acc_output:         int = int(prev["output_tokens"])                       if prev else 0
    acc_turns:          int = int(prev.get("turns", 0))                        if prev else 0
    prev_model:         str = prev.get("model", "unknown")                     if prev else "unknown"
    start_offset:       int = int(prev.get("last_byte_offset", 0))             if prev else 0

    _empty = {
        "input_tokens":          acc_input,
        "cache_creation_tokens": acc_cache_creation,
        "cache_read_tokens":     acc_cache_read,
        "output_tokens":         acc_output,
        "model":                 prev_model,
        "turns":                 acc_turns,
        "last_byte_offset":      start_offset,
    }

    if not path.exists():
        return _empty

    file_size = path.stat().st_size

    # File rotated / truncated – restart from the beginning
    if start_offset > file_size:
        start_offset = 0
        acc_input = acc_cache_creation = acc_cache_read = acc_output = acc_turns = 0
        prev_model = "unknown"

    # Nothing new to read
    if start_offset == file_size:
        return _empty

    new_input          = 0
    new_cache_creation = 0
    new_cache_read     = 0
    new_output         = 0
    new_turns          = 0
    model_counts: Counter = Counter()

    try:
        with open(path, "rb") as f:
            f.seek(start_offset)
            raw = f.read()

        # Only process complete lines (ending with \n).
        # The last bytes may belong to a line still being written.
        last_nl = raw.rfind(b"\n")
        if last_nl < 0:
            return _empty  # no complete new lines yet

        complete = raw[: last_nl + 1].decode("utf-8", errors="replace")
        new_offset = start_offset + last_nl + 1

        seen_in_chunk: set[str] = set()
        for line in complete.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") != "assistant":
                continue

            request_id = obj.get("requestId")
            if request_id:
                if request_id in seen_in_chunk:
                    continue
                seen_in_chunk.add(request_id)

            new_turns += 1

            msg = obj.get("message") or {}
            if not isinstance(msg, dict):
                continue

            model_field = msg.get("model")
            if isinstance(model_field, str) and model_field:
                model_counts[model_field] += 1

            # Read ONLY the four top-level token fields.
            # usage["iterations"] contains per-step breakdowns of the
            # same totals; summing from it would double-count every token.
            usage = msg.get("usage") or {}
            if isinstance(usage, dict):
                new_input          += int(usage.get("input_tokens")                or 0)
                new_cache_creation += int(usage.get("cache_creation_input_tokens") or 0)
                new_cache_read     += int(usage.get("cache_read_input_tokens")     or 0)
                new_output         += int(usage.get("output_tokens")               or 0)

    except Exception as exc:
        _log.error("_incremental_parse failed for %s: %s", transcript_path, exc)
        return _empty

    total_input          = acc_input          + new_input
    total_cache_creation = acc_cache_creation + new_cache_creation
    total_cache_read     = acc_cache_read     + new_cache_read
    total_output         = acc_output         + new_output
    total_turns          = acc_turns          + new_turns
    model = model_counts.most_common(1)[0][0] if model_counts else prev_model

    effective_input = total_input + total_cache_creation
    if effective_input > _SANITY_LIMIT:
        _log.warning(
            "_incremental_parse: effective_input=%d (input=%d + cache_creation=%d) "
            "exceeds %d for %s (long session – value recorded as-is)",
            effective_input, total_input, total_cache_creation,
            _SANITY_LIMIT, transcript_path,
        )

    return {
        "input_tokens":          total_input,
        "cache_creation_tokens": total_cache_creation,
        "cache_read_tokens":     total_cache_read,
        "output_tokens":         total_output,
        "model":                 model,
        "turns":                 total_turns,
        "last_byte_offset":      new_offset,
    }


class LiveTracker:
    def __init__(self, project_path: str | None):
        self.project_name: str | None = None
        self._store: TraceStore | None = None

        if project_path:
            try:
                store = _get_default_store()
                if store is not None:
                    self._store = store
                    resolved = Path(project_path).resolve()
                    for proj in store.list_projects():
                        proj_resolved = Path(proj["path"]).resolve()
                        # 1. Exact match
                        if resolved == proj_resolved:
                            self.project_name = proj["name"]
                            break
                        # 2. Ancestor match: cwd is inside the registered project path
                        #    (handles the common case where Claude Code passes the
                        #    currently-open subdirectory, e.g. /project/app/ui)
                        try:
                            resolved.relative_to(proj_resolved)
                            self.project_name = proj["name"]
                            break
                        except ValueError:
                            pass
                        # 3. Name fallback: last path component matches
                        if resolved.name == proj_resolved.name:
                            self.project_name = proj["name"]
                            break
            except Exception as exc:
                _log.error("LiveTracker.__init__ failed for %s: %s", project_path, exc)

    def update(self, transcript_path: str, cwd: str) -> dict:
        """Incrementally parse the transcript and write ~/.trace/live_session.json.

        On the very first PostToolUse of a session the transcript may not be
        fully flushed.  If parsing yields 0 tokens we wait 500 ms and retry
        once (from offset 0).  Either way we always write the file so the
        dashboard immediately shows the pulsing dot.

        Returns the written dict.
        """
        session_id = Path(transcript_path).stem

        # Load previous state for incremental parsing (same session only)
        prev = _load_prev_state(session_id)

        usage = _incremental_parse(transcript_path, prev)

        # Retry once on the very first call if transcript not yet flushed
        is_fresh_session = prev is None
        if is_fresh_session and usage["input_tokens"] == 0 and usage["output_tokens"] == 0:
            time.sleep(0.5)
            usage = _incremental_parse(transcript_path, None)

        input_tokens          = usage["input_tokens"]
        cache_creation_tokens = usage.get("cache_creation_tokens", 0)
        cache_read_tokens     = usage.get("cache_read_tokens", 0)
        output_tokens         = usage["output_tokens"]
        model                 = usage["model"]
        turns                 = usage["turns"]
        last_byte_offset      = usage["last_byte_offset"]
        initializing          = (input_tokens == 0 and cache_creation_tokens == 0
                                 and output_tokens == 0)

        # Cost calculation – all four token types at their respective rates
        cost_usd = 0.0
        try:
            store = self._store or _get_default_store()
            if store is not None:
                cost_usd = store.calculate_cost(
                    model, input_tokens, output_tokens,
                    cache_creation_tokens, cache_read_tokens,
                )
        except Exception:
            pass

        # Health based on effective context consumption (cache_read excluded –
        # it re-counts cached context on every request and would inflate the total
        # to millions of tokens for a session that never exceeded 200K).
        health = "green"
        health_store = None
        try:
            health_store = self._store or _get_default_store()
            if health_store is not None:
                health_cfg = health_store.config.get("session_health", {})
                warn_tokens = health_cfg.get("warn_tokens", 80_000)
                critical_tokens = health_cfg.get("critical_tokens", 150_000)
                total = input_tokens + cache_creation_tokens + output_tokens
                if total >= critical_tokens:
                    health = "red"
                elif total >= warn_tokens:
                    health = "yellow"
        except Exception:
            pass

        # Notify on health escalation (green→yellow, green/yellow→red).
        # De-duplicates by comparing to the previous health stored in the session file.
        prev_health = (prev or {}).get("health", "green")
        if (
            _HEALTH_ORD.get(health, 0) > _HEALTH_ORD.get(prev_health, 0)
            and health_store is not None
        ):
            try:
                from engine.notifier import notify as _notify
                _notify(
                    _HEALTH_STATUS[health],
                    input_tokens + cache_creation_tokens + output_tokens,
                    self.project_name or "unknown",
                    health_store.config,
                )
            except Exception as exc:
                _log.error("LiveTracker.update: notify failed: %s", exc)

        data: dict = {
            "session_id":            session_id,
            "project":               self.project_name or "unknown",
            "cwd":                   cwd,
            "input_tokens":          input_tokens,
            "cache_creation_tokens": cache_creation_tokens,
            "cache_read_tokens":     cache_read_tokens,
            "output_tokens":         output_tokens,
            "cost_usd":              cost_usd,
            "model":                 model,
            "turns":                 turns,
            "health":                health,
            "initializing":          initializing,
            "last_byte_offset":      last_byte_offset,
            "updated_at":            datetime.now().isoformat(timespec="seconds"),
        }

        try:
            _LIVE_DIR.mkdir(parents=True, exist_ok=True)
            session_file = _LIVE_DIR / f"{session_id}.json"
            session_file.write_text(json.dumps(data, indent=2))
            # Migrate legacy live_session.json on first write to new layout
            if _LIVE_PATH.exists():
                try:
                    _LIVE_PATH.unlink()
                except Exception:
                    pass
        except Exception as exc:
            _log.error("LiveTracker.update: failed to write live session: %s", exc)

        # Persist health state snapshot (survive browser refresh + session end)
        self._write_last_health(data)

        return data

    def clear(self, session_id: str | None = None) -> None:
        """Delete live session file(s) and last_health.json.

        If *session_id* is given, only that session's file is removed.
        Otherwise all files in _LIVE_DIR are removed (dashboard clear).
        """
        try:
            if _LIVE_DIR.is_dir():
                targets = (
                    [_LIVE_DIR / f"{session_id}.json"]
                    if session_id
                    else list(_LIVE_DIR.glob("*.json"))
                )
                for f in targets:
                    try:
                        if f.exists():
                            f.unlink()
                    except Exception as exc:
                        _log.error("LiveTracker.clear: %s", exc)
        except Exception as exc:
            _log.error("LiveTracker.clear (dir): %s", exc)
        # Always clear legacy file (no session_id scoping needed)
        try:
            if _LIVE_PATH.exists():
                _LIVE_PATH.unlink()
        except Exception as exc:
            _log.error("LiveTracker.clear (legacy): %s", exc)
        try:
            if _LAST_HEALTH_PATH.exists():
                _LAST_HEALTH_PATH.unlink()
        except Exception as exc:
            _log.error("LiveTracker.clear (last_health): %s", exc)

    def get_all_active(self) -> list[dict]:
        """Return all non-stale active sessions sorted by updated_at descending."""
        now = time.time()
        result: list[dict] = []
        try:
            if not _LIVE_DIR.is_dir():
                return result
            for f in _LIVE_DIR.glob("*.json"):
                try:
                    if now - f.stat().st_mtime > _STALE_SECONDS:
                        continue
                    data = json.loads(f.read_text())
                    result.append(data)
                except Exception:
                    continue
        except Exception:
            pass
        result.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
        return result

    def get_live(self) -> dict | None:
        """Return the most recent active session, or None if none are active."""
        sessions = self.get_all_active()
        return sessions[0] if sessions else None

    def _write_last_health(self, live_data: dict) -> None:
        """Persist health snapshot to ~/.trace/last_health.json on every status update.

        Writes on every call (ok, warn, reset) so the health bar is always visible
        from the first turn. Never deletes the file – deletion is only done by
        LiveTracker.clear() when the user explicitly clears the session.
        """
        health = live_data.get("health", "green")
        session_id = live_data.get("session_id")
        project = live_data.get("project", "unknown")
        turns = live_data.get("turns", 0)
        total_tokens = (
            live_data.get("input_tokens", 0)
            + live_data.get("cache_creation_tokens", 0)
            + live_data.get("output_tokens", 0)
        )

        # Map health colors to status strings (API uses warn/reset, internal uses yellow/red)
        status = "ok"
        if health == "red":
            status = "reset"
        elif health == "yellow":
            status = "warn"

        try:
            snapshot = {
                "status": status,
                "tokens": total_tokens,
                "turns": turns,
                "project": project,
                "session_id": session_id,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            TRACE_HOME.mkdir(parents=True, exist_ok=True)
            _LAST_HEALTH_PATH.write_text(json.dumps(snapshot, indent=2))
            _log.info("Wrote last_health.json: status=%s, tokens=%d, turns=%d, project=%s", status, total_tokens, turns, project)
        except Exception as exc:
            _log.error("LiveTracker._write_last_health: %s", exc)

    def get_last_health(self) -> dict | None:
        """Return last known health snapshot, or None if absent."""
        if not _LAST_HEALTH_PATH.exists():
            return None
        try:
            return json.loads(_LAST_HEALTH_PATH.read_text())
        except Exception as exc:
            _log.error("LiveTracker.get_last_health: %s", exc)
            return None
