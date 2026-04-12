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

# Conventional-commit prefixes that don't need doc synthesis.
# .trace_sync is still advanced so check_drift() stays accurate.
SKIP_PREFIXES: list[str] = [
    "chore:",
    "chore(",
    "docs:",
    "docs(",
    "style:",
    "style(",
    "test:",
    "test(",
]


def should_skip(commit_message: str) -> bool:
    """Return True if the commit message prefix signals non-code changes.

    Returns False for empty / unrecognised messages so unknown commits are
    always processed (when in doubt, synthesise).
    """
    msg = commit_message.lower().strip()
    if not msg:
        return False
    return any(msg.startswith(p) for p in SKIP_PREFIXES)


def run(project_path: str) -> None:
    """Check for drift and update AI_CONTEXT.md if doc-relevant changes exist."""
    try:
        store = TraceStore.default()
        synth = DocSynthesizer(project_path, config_path=str(store.config_path))

        # Read the latest commit message to decide whether synthesis is needed
        try:
            latest_commit = synth.watcher.repo.head.commit
            latest_msg    = latest_commit.message
            latest_hash   = latest_commit.hexsha[:7]
        except Exception:
            latest_msg  = ""
            latest_hash = ""

        if should_skip(latest_msg):
            # Advance .trace_sync so drift detection stays accurate
            if latest_hash:
                synth.update_last_synced(latest_hash)
            _log.info(
                "Skipped doc synthesis for: %s",
                latest_msg.strip()[:80],
            )
            return

        # Determine baseline – use .trace_sync or fall back to oldest commit
        last_hash = synth.get_last_synced()
        if last_hash is None:
            all_commits = list(synth.watcher.repo.iter_commits())
            last_hash = all_commits[-1].hexsha if all_commits else ""

        if not last_hash:
            return  # empty repo

        drift = synth.check_drift(last_hash)

        if not drift["is_stale"] or not drift["doc_relevant_changes"]:
            return  # nothing worth updating

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
