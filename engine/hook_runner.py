"""Git hook entry point – called by .git/hooks/post-commit after every commit.

Never raises: all exceptions are silently swallowed so the hook can never
block a commit.
"""
from __future__ import annotations

import logging
import sys
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


def run(project_path: str) -> None:
    """Check for drift and update AI_CONTEXT.md if needed.

    Delegates to DocSynthesizer.update_if_stale(), which fires when either
    doc-relevant files changed since last sync or AI_CONTEXT.md is older than
    the staleness threshold. Never raises – the post-commit hook must not
    block a commit.
    """
    try:
        store = TraceStore.default()
        synth = DocSynthesizer(project_path, config_path=str(store.config_path))
        synth.update_if_stale()
    except Exception:
        pass  # never block a commit


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else ".")
