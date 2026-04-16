"""Tests for engine/hook_runner.py – every commit type triggers synthesis.

Covers:
  - chore:/docs:/test: commits with doc-relevant files DO trigger synthesis
  - feat:/fix: commits still trigger synthesis
  - No-op: no doc-relevant changes + fresh AI_CONTEXT.md → no synthesis
  - Staleness fallback: AI_CONTEXT.md > 2 days old forces synthesis even
    when no doc-relevant files changed
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import git
import pytest

from engine.hook_runner import run

# ---------------------------------------------------------------------------
# Helpers
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
# Commit-type filtering removed – chore/docs/test now trigger synthesis
# ---------------------------------------------------------------------------

def test_chore_commit_triggers_synthesis(tmp_path):
    """chore: + doc-relevant file must trigger synthesis (no prefix filtering)."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    new_hash = _add_commit(
        tmp_path, repo, "engine/module.py",
        content="# engine update", msg="chore: tidy engine module",
    )

    run(str(tmp_path))

    synced = (tmp_path / ".trace_sync").read_text(encoding="utf-8").strip()
    assert synced == new_hash
    context_after = (tmp_path / "AI_CONTEXT.md").read_text(encoding="utf-8")
    assert "Auto-synced" in context_after


def test_docs_commit_triggers_synthesis(tmp_path):
    """docs: + doc-relevant file must trigger synthesis."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    new_hash = _add_commit(
        tmp_path, repo, "engine/doc.py",
        content="# doc update", msg="docs: add docstrings",
    )

    run(str(tmp_path))

    synced = (tmp_path / ".trace_sync").read_text(encoding="utf-8").strip()
    assert synced == new_hash
    context_after = (tmp_path / "AI_CONTEXT.md").read_text(encoding="utf-8")
    assert "Auto-synced" in context_after


def test_test_commit_triggers_synthesis(tmp_path):
    """test: + doc-relevant file must trigger synthesis."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    new_hash = _add_commit(
        tmp_path, repo, "tests/test_new.py",
        content="# tests", msg="test: add integration tests",
    )

    run(str(tmp_path))

    synced = (tmp_path / ".trace_sync").read_text(encoding="utf-8").strip()
    assert synced == new_hash
    context_after = (tmp_path / "AI_CONTEXT.md").read_text(encoding="utf-8")
    assert "Auto-synced" in context_after


# ---------------------------------------------------------------------------
# feat:/fix: commits still trigger synthesis
# ---------------------------------------------------------------------------

def test_feat_commit_triggers_synthesis(tmp_path):
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    new_hash = _add_commit(
        tmp_path, repo, "engine/feature.py",
        content="# new feature", msg="feat: add new engine feature",
    )

    run(str(tmp_path))

    synced = (tmp_path / ".trace_sync").read_text(encoding="utf-8").strip()
    assert synced == new_hash
    context_after = (tmp_path / "AI_CONTEXT.md").read_text(encoding="utf-8")
    assert "Auto-synced" in context_after


def test_fix_commit_triggers_synthesis(tmp_path):
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


# ---------------------------------------------------------------------------
# File-change guard still works
# ---------------------------------------------------------------------------

def test_no_synthesis_when_fresh_and_no_doc_relevant_changes(tmp_path):
    """With a fresh AI_CONTEXT.md and no doc-relevant file changes, no synthesis."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    mtime_before = (tmp_path / "AI_CONTEXT.md").stat().st_mtime

    _add_commit(
        tmp_path, repo, "images/logo.png",
        content="fake binary", msg="chore: add logo",
    )

    run(str(tmp_path))

    assert (tmp_path / "AI_CONTEXT.md").stat().st_mtime == mtime_before


# ---------------------------------------------------------------------------
# Staleness fallback
# ---------------------------------------------------------------------------

def test_staleness_fallback_forces_synthesis_without_doc_relevant_changes(tmp_path):
    """When AI_CONTEXT.md is >2 days old, synthesis is forced even if no
    doc-relevant files changed."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    # Make AI_CONTEXT.md appear 3 days old
    context = tmp_path / "AI_CONTEXT.md"
    old_time = time.time() - (3 * 24 * 3600)
    os.utime(context, (old_time, old_time))

    # Commit a non-doc-relevant file
    _add_commit(tmp_path, repo, "images/logo.png", content="fake", msg="chore: add logo")

    run(str(tmp_path))

    context_after = context.read_text(encoding="utf-8")
    assert "Auto-synced" in context_after


def test_staleness_fallback_inactive_when_context_fresh(tmp_path):
    """With a fresh AI_CONTEXT.md, a non-doc-relevant commit must NOT synthesise."""
    repo = _init_repo(tmp_path)
    initial_hash = repo.head.commit.hexsha[:7]
    (tmp_path / ".trace_sync").write_text(initial_hash, encoding="utf-8")

    mtime_before = (tmp_path / "AI_CONTEXT.md").stat().st_mtime

    _add_commit(tmp_path, repo, "images/logo.png", content="fake", msg="chore: add logo")

    run(str(tmp_path))

    assert (tmp_path / "AI_CONTEXT.md").stat().st_mtime == mtime_before
