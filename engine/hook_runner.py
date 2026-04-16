"""Git hook entry point – called by .git/hooks/post-commit after every commit.

Never raises: all exceptions are silently swallowed so the hook can never
block a commit.
"""
from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

# Ensure TRACE root is importable when invoked directly by the git hook
_TRACE_ROOT = Path(__file__).parents[1]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.doc_synthesizer import DocSynthesizer  # noqa: E402 (after path setup)
from engine.store import TraceStore, TRACE_HOME  # noqa: E402

_LOG_FILE = TRACE_HOME / "session_logger.log"
logging.basicConfig(
    filename=str(_LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
_log = logging.getLogger(__name__)

_STALE_DAYS = 2


def run(project_path: str) -> None:
    """Check for drift and update AI_CONTEXT.md if needed.

    Synthesis runs when either:
      - there are doc-relevant file changes since last sync, OR
      - AI_CONTEXT.md is older than _STALE_DAYS days (staleness fallback)
    """
    try:
        store = TraceStore.default()
        synth = DocSynthesizer(project_path, config_path=str(store.config_path))

        # Determine baseline – use .trace_sync or fall back to oldest commit
        last_hash = synth.get_last_synced()
        if last_hash is None:
            all_commits = list(synth.watcher.repo.iter_commits())
            last_hash = all_commits[-1].hexsha if all_commits else ""

        if not last_hash:
            return  # empty repo

        drift = synth.check_drift(last_hash)

        if not drift["is_stale"]:
            return  # already up to date

        age_days = synth.get_context_age_days()
        force_by_age = age_days is not None and age_days > _STALE_DAYS

        if not drift["doc_relevant_changes"] and not force_by_age:
            return  # no meaningful changes and context is fresh

        today = date.today().isoformat()
        synth.apply_section_update(
            "Last updated",
            f"{today} – Auto-synced {drift['commits_behind']} commit(s) "
            f"to {drift['current_hash']}",
        )
        synth.update_last_synced(drift["current_hash"])

    except Exception:
        pass  # never block a commit


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else ".")
