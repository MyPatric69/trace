"""Integration tests for server/tools/context.py – MCP tool layer."""
from pathlib import Path

import git
import pytest

import server.tools.context as ctx_module
from server.tools.context import check_drift, update_context
from engine.store import TraceStore

# Minimal AI_CONTEXT.md for the test git repo
_TEST_CONTEXT = """\
# AI_CONTEXT.md

## Project

Test project.

---

## Next steps

- [ ] Nothing yet

---

## Last updated

2026-01-01
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx_env(tmp_path, tmp_store, monkeypatch):
    """
    Full context tool environment:
    - tmp_path holds a real git repo with AI_CONTEXT.md
    - 'myproject' registered in tmp_store pointing at tmp_path
    - ctx_module._store monkeypatched to return tmp_store
    """
    repo = git.Repo.init(str(tmp_path))

    # Neutralise any globally-installed post-commit hook (e.g. TRACE's own
    # ~/.git-template hook) so it cannot overwrite .trace_sync during test
    # commits and corrupt the fixture state.  Only this repo is affected.
    hook_path = tmp_path / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(exist_ok=True)
    hook_path.write_text("#!/bin/sh\nexit 0\n")
    hook_path.chmod(0o755)

    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")

    (tmp_path / "AI_CONTEXT.md").write_text(_TEST_CONTEXT, encoding="utf-8")
    repo.index.add(["AI_CONTEXT.md"])
    repo.index.commit("Initial commit")

    tmp_store.add_project("myproject", str(tmp_path), "Test project")
    monkeypatch.setattr(ctx_module, "_store", lambda: tmp_store)

    return tmp_path, repo


def _add_commit(tmp_path, repo, filename: str, content: str = "# change", msg: str = "update"):
    """Helper: write a file, stage it, commit."""
    filepath = tmp_path / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    repo.index.add([filename])
    repo.index.commit(msg)
    return repo.head.commit.hexsha[:7]


def _set_synced(tmp_path, hash_: str):
    """Write hash to .trace_sync."""
    (tmp_path / ".trace_sync").write_text(hash_, encoding="utf-8")


# ---------------------------------------------------------------------------
# check_drift – structure and keys
# ---------------------------------------------------------------------------

def test_check_drift_returns_correct_structure(ctx_env):
    tmp_path, repo = ctx_env
    _set_synced(tmp_path, repo.head.commit.hexsha[:7])
    result = check_drift("myproject")

    expected_keys = {
        "status", "project", "is_stale", "commits_behind",
        "doc_relevant_changes", "changed_files", "current_hash", "recommendation",
        "ai_context_age_days",
    }
    assert expected_keys == set(result.keys())


# ---------------------------------------------------------------------------
# check_drift – up to date
# ---------------------------------------------------------------------------

def test_check_drift_up_to_date_when_synced(ctx_env):
    tmp_path, repo = ctx_env
    _set_synced(tmp_path, repo.head.commit.hexsha[:7])

    result = check_drift("myproject")

    assert result["status"] == "ok"
    assert result["is_stale"] is False
    assert result["commits_behind"] == 0
    assert result["recommendation"] == "AI_CONTEXT.md is up to date"


# ---------------------------------------------------------------------------
# check_drift – stale
# ---------------------------------------------------------------------------

def test_check_drift_stale_when_behind(ctx_env):
    tmp_path, repo = ctx_env
    _set_synced(tmp_path, repo.head.commit.hexsha[:7])

    _add_commit(tmp_path, repo, "engine/new.py", msg="feat: add engine module")

    result = check_drift("myproject")

    assert result["is_stale"] is True
    assert result["commits_behind"] >= 1
    assert isinstance(result["changed_files"], list)


def test_check_drift_recommendation_stale_with_relevant_changes(ctx_env):
    tmp_path, repo = ctx_env
    _set_synced(tmp_path, repo.head.commit.hexsha[:7])

    _add_commit(tmp_path, repo, "engine/new.py", msg="feat: add engine module")

    result = check_drift("myproject")

    assert result["doc_relevant_changes"] is True
    assert "update_context()" in result["recommendation"]


def test_check_drift_recommendation_stale_no_relevant_changes(ctx_env):
    tmp_path, repo = ctx_env
    _set_synced(tmp_path, repo.head.commit.hexsha[:7])

    _add_commit(tmp_path, repo, "data.csv", content="a,b\n1,2", msg="add csv")

    result = check_drift("myproject")

    assert result["is_stale"] is True
    assert result["doc_relevant_changes"] is False
    assert "no doc-relevant changes" in result["recommendation"]


# ---------------------------------------------------------------------------
# check_drift – unknown project
# ---------------------------------------------------------------------------

def test_check_drift_unknown_project_returns_error(ctx_env):
    result = check_drift("ghost-project")
    assert result["status"] == "error"
    assert "ghost-project" in result["message"]


# ---------------------------------------------------------------------------
# update_context – dry_run
# ---------------------------------------------------------------------------

def test_update_context_dry_run_returns_prompt(ctx_env):
    tmp_path, repo = ctx_env
    initial_hash = repo.head.commit.hexsha[:7]
    _set_synced(tmp_path, initial_hash)

    _add_commit(tmp_path, repo, "engine/new.py", msg="feat: add module")

    result = update_context("myproject", dry_run=True)

    assert result["status"] == "dry_run"
    assert isinstance(result["update_prompt"], str)
    assert len(result["update_prompt"]) > 0
    assert result["sections_updated"] == []
    # Dry run must not advance .trace_sync – it should still hold the initial hash
    assert (tmp_path / ".trace_sync").read_text().strip() == initial_hash


# ---------------------------------------------------------------------------
# update_context – already up to date
# ---------------------------------------------------------------------------

def test_update_context_up_to_date_status(ctx_env):
    tmp_path, repo = ctx_env
    _set_synced(tmp_path, repo.head.commit.hexsha[:7])

    result = update_context("myproject")

    assert result["status"] == "up_to_date"
    assert result["commits_synced"] == 0
    assert result["sections_updated"] == []


# ---------------------------------------------------------------------------
# update_context – unknown project
# ---------------------------------------------------------------------------

def test_update_context_unknown_project_returns_error(ctx_env):
    result = update_context("ghost-project")
    assert result["status"] == "error"
    assert "ghost-project" in result["message"]


# ---------------------------------------------------------------------------
# update_context – actually applies changes
# ---------------------------------------------------------------------------

def test_update_context_applies_updates_and_syncs_hash(ctx_env):
    tmp_path, repo = ctx_env
    initial_hash = repo.head.commit.hexsha[:7]
    _set_synced(tmp_path, initial_hash)

    _add_commit(tmp_path, repo, "engine/module.py", msg="feat: add engine module")
    new_hash = repo.head.commit.hexsha[:7]

    result = update_context("myproject")

    assert result["status"] == "ok"
    assert result["commits_synced"] >= 1
    assert "Last updated" in result["sections_updated"]
    assert "engine/module.py" in result["files_affected"]

    # .trace_sync must now hold the new HEAD
    synced = (tmp_path / ".trace_sync").read_text().strip()
    assert synced == new_hash

    # AI_CONTEXT.md must be updated
    context = (tmp_path / "AI_CONTEXT.md").read_text()
    assert new_hash in context  # new hash appears in Last updated section
