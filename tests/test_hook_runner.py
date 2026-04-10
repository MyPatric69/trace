"""Tests for engine/hook_runner.py."""
from pathlib import Path

import git
import pytest

from engine.hook_runner import run

REPO_ROOT = Path(__file__).parents[1]

_TEST_CONTEXT = """\
# AI_CONTEXT.md

## Project

Test project.

---

## Last updated

2026-01-01
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_repo(tmp_path, context_content: str = _TEST_CONTEXT):
    repo = git.Repo.init(str(tmp_path))
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    (tmp_path / "AI_CONTEXT.md").write_text(context_content, encoding="utf-8")
    repo.index.add(["AI_CONTEXT.md"])
    repo.index.commit("Initial commit")
    return repo


def _add_commit(tmp_path, repo, filename: str, content: str = "# x", msg: str = "update"):
    filepath = tmp_path / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    repo.index.add([filename])
    repo.index.commit(msg)
    return repo.head.commit.hexsha[:7]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_run_completes_without_raising_on_fresh_repo(tmp_path):
    """run() must not raise for any valid git repo."""
    _init_repo(tmp_path)
    run(str(tmp_path))  # should complete silently


def test_run_silent_when_not_stale(tmp_path):
    """When .trace_sync matches HEAD, run() does nothing."""
    repo = _init_repo(tmp_path)
    current_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(current_hash, encoding="utf-8")

    original_mtime = (tmp_path / "AI_CONTEXT.md").stat().st_mtime
    run(str(tmp_path))

    # AI_CONTEXT.md must not have been touched
    assert (tmp_path / "AI_CONTEXT.md").stat().st_mtime == original_mtime
    # .trace_sync must still hold the original hash
    assert (tmp_path / ".trace_sync").read_text().strip() == current_hash


def test_run_handles_invalid_path_gracefully(tmp_path):
    """run() must not raise for a path that is not a git repo."""
    non_git = tmp_path / "not_a_repo"
    non_git.mkdir()
    run(str(non_git))  # must not raise


def test_run_handles_completely_invalid_path_gracefully():
    """run() must not raise for a path that does not exist."""
    run("/this/path/does/not/exist")


def test_run_updates_trace_sync_when_stale(tmp_path):
    """When stale with doc-relevant changes, run() advances .trace_sync."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    # Add a doc-relevant commit (engine/ file → is_doc_relevant=True)
    new_hash = _add_commit(tmp_path, repo, "engine/module.py", msg="feat: new module")

    run(str(tmp_path))

    synced = (tmp_path / ".trace_sync").read_text().strip()
    assert synced == new_hash


def test_run_no_update_when_changes_not_doc_relevant(tmp_path):
    """When stale but no doc-relevant files changed, run() leaves .trace_sync unchanged."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    # Non-doc-relevant file (CSV is not matched by is_doc_relevant)
    _add_commit(tmp_path, repo, "data.csv", content="a,b\n1,2", msg="add data")

    run(str(tmp_path))

    synced = (tmp_path / ".trace_sync").read_text().strip()
    assert synced == initial_hash  # unchanged


def test_run_on_trace_repo_does_not_raise():
    """Smoke test: run() on the real TRACE repo completes without error."""
    run(str(REPO_ROOT))
