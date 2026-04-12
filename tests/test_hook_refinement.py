"""Tests for v0.3.0 Feature 3 – Hook Refinement (engine/hook_runner.py).

Covers:
  - should_skip() returns True for chore/docs/style/test prefixes
  - should_skip() returns False for feat/fix/refactor/unknown/empty
  - Case-insensitivity
  - Integration: skip commit → .trace_sync advances, AI_CONTEXT.md untouched
  - Integration: feat: commit → synthesis runs, AI_CONTEXT.md updated
"""
from __future__ import annotations

from pathlib import Path

import git
import pytest

from engine.hook_runner import run, should_skip

# ---------------------------------------------------------------------------
# Helpers (mirrors test_hook_runner.py)
# ---------------------------------------------------------------------------

_TEST_CONTEXT = """\
# AI_CONTEXT.md

## Project

Test project.

---

## Last updated

2026-01-01
"""


def _init_repo(tmp_path, context_content: str = _TEST_CONTEXT):
    repo = git.Repo.init(str(tmp_path))
    # Prevent the globally-installed post-commit hook from interfering
    hook_path = tmp_path / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(exist_ok=True)
    hook_path.write_text("#!/bin/sh\nexit 0\n")
    hook_path.chmod(0o755)
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
# should_skip() – True cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("msg", [
    "chore: update deps",
    "chore(deps): bump requests to 2.32",
    "docs: update README",
    "docs(api): add endpoint reference",
    "style: reformat with black",
    "style(lint): fix whitespace",
    "test: add store tests",
    "test(store): cover edge cases",
])
def test_should_skip_returns_true_for_skip_prefixes(msg):
    assert should_skip(msg) is True


# ---------------------------------------------------------------------------
# should_skip() – False cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("msg", [
    "feat: add token calculator",
    "fix: correct cost calculation",
    "refactor: extract helper",
    "perf: speed up query",
    "ci: update workflow",
    "build: upgrade Python",
    "unknown prefix message",
    "",
    "   ",
])
def test_should_skip_returns_false_for_non_skip_prefixes(msg):
    assert should_skip(msg) is False


# ---------------------------------------------------------------------------
# should_skip() – case-insensitivity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("msg", [
    "CHORE: update deps",
    "Docs: add README",
    "STYLE: fix formatting",
    "TEST: add unit tests",
    "Chore(CI): update workflow",
    "DOCS(api): reference",
])
def test_should_skip_is_case_insensitive(msg):
    assert should_skip(msg) is True


# ---------------------------------------------------------------------------
# Integration – skip commit: .trace_sync advances, AI_CONTEXT.md untouched
# ---------------------------------------------------------------------------

def test_skip_commit_advances_trace_sync_but_not_context(tmp_path):
    """A chore: commit with a doc-relevant file should advance .trace_sync
    but leave AI_CONTEXT.md completely unchanged."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    context_before = (tmp_path / "AI_CONTEXT.md").read_text(encoding="utf-8")
    mtime_before = (tmp_path / "AI_CONTEXT.md").stat().st_mtime

    # Add a doc-relevant commit with a skip prefix
    new_hash = _add_commit(
        tmp_path, repo, "engine/module.py",
        content="# engine update", msg="chore: tidy engine module",
    )

    run(str(tmp_path))

    # .trace_sync must have advanced to the new commit
    synced = (tmp_path / ".trace_sync").read_text(encoding="utf-8").strip()
    assert synced == new_hash

    # AI_CONTEXT.md must be completely untouched
    assert (tmp_path / "AI_CONTEXT.md").stat().st_mtime == mtime_before
    assert (tmp_path / "AI_CONTEXT.md").read_text(encoding="utf-8") == context_before


def test_docs_commit_advances_trace_sync_but_not_context(tmp_path):
    """A docs: commit should behave identically to chore:."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    mtime_before = (tmp_path / "AI_CONTEXT.md").stat().st_mtime

    new_hash = _add_commit(
        tmp_path, repo, "engine/doc.py",
        content="# doc update", msg="docs: add docstrings",
    )

    run(str(tmp_path))

    assert (tmp_path / ".trace_sync").read_text(encoding="utf-8").strip() == new_hash
    assert (tmp_path / "AI_CONTEXT.md").stat().st_mtime == mtime_before


def test_test_commit_advances_trace_sync_but_not_context(tmp_path):
    """A test: commit should not trigger synthesis."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    mtime_before = (tmp_path / "AI_CONTEXT.md").stat().st_mtime

    new_hash = _add_commit(
        tmp_path, repo, "tests/test_new.py",
        content="# tests", msg="test: add integration tests",
    )

    run(str(tmp_path))

    assert (tmp_path / ".trace_sync").read_text(encoding="utf-8").strip() == new_hash
    assert (tmp_path / "AI_CONTEXT.md").stat().st_mtime == mtime_before


# ---------------------------------------------------------------------------
# Integration – feat: commit triggers synthesis
# ---------------------------------------------------------------------------

def test_feat_commit_triggers_synthesis(tmp_path):
    """A feat: commit with a doc-relevant file should update AI_CONTEXT.md
    and advance .trace_sync."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    # Add a doc-relevant commit (engine/ triggers is_doc_relevant=True)
    new_hash = _add_commit(
        tmp_path, repo, "engine/feature.py",
        content="# new feature", msg="feat: add new engine feature",
    )

    run(str(tmp_path))

    # .trace_sync must advance
    synced = (tmp_path / ".trace_sync").read_text(encoding="utf-8").strip()
    assert synced == new_hash

    # AI_CONTEXT.md must have been updated (Last updated section modified)
    context_after = (tmp_path / "AI_CONTEXT.md").read_text(encoding="utf-8")
    assert "Auto-synced" in context_after


def test_fix_commit_triggers_synthesis(tmp_path):
    """A fix: commit with a doc-relevant file should also trigger synthesis."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    new_hash = _add_commit(
        tmp_path, repo, "engine/bug_fix.py",
        content="# bug fix", msg="fix: correct off-by-one in store",
    )

    run(str(tmp_path))

    synced = (tmp_path / ".trace_sync").read_text(encoding="utf-8").strip()
    assert synced == new_hash
    context_after = (tmp_path / "AI_CONTEXT.md").read_text(encoding="utf-8")
    assert "Auto-synced" in context_after
