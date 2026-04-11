"""Tests for engine/doc_synthesizer.py."""
from pathlib import Path

import git
import pytest

from engine.doc_synthesizer import DocSynthesizer

REPO_ROOT = Path(__file__).parents[1]
REAL_CONFIG = str(REPO_ROOT / "trace_config.yaml")

# Minimal AI_CONTEXT.md used in tmp repo tests
_TEST_CONTEXT = """\
# AI_CONTEXT.md

## Project

Original project info.

---

## What TRACE does

Original description.

---

## Last updated

2026-04-01
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def real_synth() -> DocSynthesizer:
    """DocSynthesizer pointing at the real TRACE repo – read-only git operations."""
    return DocSynthesizer(str(REPO_ROOT), config_path=REAL_CONFIG)


@pytest.fixture
def tmp_synth(tmp_path) -> DocSynthesizer:
    """DocSynthesizer with a fresh git repo and AI_CONTEXT.md in tmp_path."""
    repo = git.Repo.init(str(tmp_path))
    # Neutralise any globally-installed post-commit hook so it cannot call
    # auto_register and write temp project paths to ~/.trace/trace.db.
    hook_path = tmp_path / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(exist_ok=True)
    hook_path.write_text("#!/bin/sh\nexit 0\n")
    hook_path.chmod(0o755)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")

    context_file = tmp_path / "AI_CONTEXT.md"
    context_file.write_text(_TEST_CONTEXT, encoding="utf-8")
    repo.index.add(["AI_CONTEXT.md"])
    repo.index.commit("Initial commit")

    return DocSynthesizer(str(tmp_path), config_path=REAL_CONFIG)


# ---------------------------------------------------------------------------
# get_context_path
# ---------------------------------------------------------------------------

def test_get_context_path_returns_path_object(tmp_synth):
    path = tmp_synth.get_context_path()
    assert isinstance(path, Path)


def test_get_context_path_existing_file_not_overwritten(tmp_synth):
    original = tmp_synth.read_context()
    tmp_synth.get_context_path()  # should not overwrite
    assert tmp_synth.read_context() == original


def test_get_context_path_creates_template_when_missing(tmp_path):
    """If AI_CONTEXT.md is absent, get_context_path() creates it from template."""
    repo = git.Repo.init(str(tmp_path))
    hook_path = tmp_path / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(exist_ok=True)
    hook_path.write_text("#!/bin/sh\nexit 0\n")
    hook_path.chmod(0o755)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    # Commit something so the repo has at least one commit
    dummy = tmp_path / "README.md"
    dummy.write_text("hi")
    repo.index.add(["README.md"])
    repo.index.commit("init")

    synth = DocSynthesizer(str(tmp_path), config_path=REAL_CONFIG)
    assert not (tmp_path / "AI_CONTEXT.md").exists()

    path = synth.get_context_path()
    assert path.exists()
    content = path.read_text()
    assert "# AI_CONTEXT.md" in content


# ---------------------------------------------------------------------------
# read_context
# ---------------------------------------------------------------------------

def test_read_context_returns_content(tmp_synth):
    content = tmp_synth.read_context()
    assert "# AI_CONTEXT.md" in content
    assert "## Project" in content


def test_read_context_returns_empty_string_when_no_file(tmp_path):
    repo = git.Repo.init(str(tmp_path))
    hook_path = tmp_path / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(exist_ok=True)
    hook_path.write_text("#!/bin/sh\nexit 0\n")
    hook_path.chmod(0o755)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    dummy = tmp_path / "x.txt"
    dummy.write_text("x")
    repo.index.add(["x.txt"])
    repo.index.commit("init")

    synth = DocSynthesizer(str(tmp_path), config_path=REAL_CONFIG)
    assert synth.read_context() == ""


# ---------------------------------------------------------------------------
# check_drift
# ---------------------------------------------------------------------------

def test_check_drift_returns_correct_keys(real_synth):
    last = real_synth.watcher.get_last_commit()["hash"]
    result = real_synth.check_drift(last)
    expected_keys = {
        "is_stale", "commits_behind", "changed_files",
        "doc_relevant_changes", "last_synced_hash", "current_hash",
    }
    assert expected_keys == set(result.keys())


def test_check_drift_not_stale_for_current_head(real_synth):
    current_hash = real_synth.watcher.get_last_commit()["hash"]
    result = real_synth.check_drift(current_hash)
    assert result["is_stale"] is False
    assert result["commits_behind"] == 0
    assert result["changed_files"] == []


def test_check_drift_stale_for_old_hash(real_synth):
    all_commits = list(real_synth.watcher.repo.iter_commits())
    if len(all_commits) < 2:
        pytest.skip("Need at least 2 commits")
    root = all_commits[-1]
    result = real_synth.check_drift(root.hexsha)
    assert result["is_stale"] is True
    assert result["commits_behind"] >= 1
    assert isinstance(result["changed_files"], list)
    assert isinstance(result["doc_relevant_changes"], bool)


def test_check_drift_stale_includes_current_hash(real_synth):
    all_commits = list(real_synth.watcher.repo.iter_commits())
    if len(all_commits) < 2:
        pytest.skip("Need at least 2 commits")
    root = all_commits[-1]
    result = real_synth.check_drift(root.hexsha)
    assert result["current_hash"] == real_synth.watcher.get_last_commit()["hash"]
    assert result["last_synced_hash"] == root.hexsha


# ---------------------------------------------------------------------------
# build_update_prompt
# ---------------------------------------------------------------------------

def test_build_update_prompt_returns_non_empty_string(real_synth):
    all_commits = list(real_synth.watcher.repo.iter_commits())
    if len(all_commits) < 2:
        pytest.skip("Need at least 2 commits")
    root = all_commits[-1]
    result = real_synth.build_update_prompt(root.hexsha)
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_update_prompt_contains_commit_info(real_synth):
    all_commits = list(real_synth.watcher.repo.iter_commits())
    if len(all_commits) < 2:
        pytest.skip("Need at least 2 commits")
    root = all_commits[-1]
    result = real_synth.build_update_prompt(root.hexsha)
    # Should mention commits and a hash
    assert "commit" in result.lower()
    assert any(c["hash"] in result for c in real_synth.watcher.get_commits_since(root.hexsha))


def test_build_update_prompt_no_commits_returns_message(real_synth):
    current = real_synth.watcher.get_last_commit()["hash"]
    result = real_synth.build_update_prompt(current)
    assert "No new commits" in result


def test_build_update_prompt_stays_within_token_budget(real_synth):
    all_commits = list(real_synth.watcher.repo.iter_commits())
    if len(all_commits) < 2:
        pytest.skip("Need at least 2 commits")
    root = all_commits[-1]
    result = real_synth.build_update_prompt(root.hexsha)
    # 3800 chars ≈ 950 tokens – well under the 1000-token limit
    assert len(result) <= 3800


# ---------------------------------------------------------------------------
# get_last_synced / update_last_synced
# ---------------------------------------------------------------------------

def test_get_last_synced_returns_none_when_no_file(tmp_synth):
    assert tmp_synth.get_last_synced() is None


def test_update_last_synced_creates_file(tmp_synth):
    tmp_synth.update_last_synced("abc1234")
    sync_file = tmp_synth.project_path / ".trace_sync"
    assert sync_file.exists()


def test_update_and_read_last_synced_roundtrip(tmp_synth):
    tmp_synth.update_last_synced("abc1234")
    assert tmp_synth.get_last_synced() == "abc1234"


def test_update_last_synced_overwrites_previous(tmp_synth):
    tmp_synth.update_last_synced("aaa1111")
    tmp_synth.update_last_synced("bbb2222")
    assert tmp_synth.get_last_synced() == "bbb2222"


# ---------------------------------------------------------------------------
# apply_section_update
# ---------------------------------------------------------------------------

def test_apply_section_update_returns_true_for_existing_section(tmp_synth):
    assert tmp_synth.apply_section_update("Project", "New project info.") is True


def test_apply_section_update_returns_false_for_missing_section(tmp_synth):
    assert tmp_synth.apply_section_update("Nonexistent Section", "content") is False


def test_apply_section_update_content_is_written(tmp_synth):
    tmp_synth.apply_section_update("Project", "Updated project info.")
    content = tmp_synth.read_context()
    assert "Updated project info." in content


def test_apply_section_update_old_content_replaced(tmp_synth):
    tmp_synth.apply_section_update("Project", "Brand new content.")
    content = tmp_synth.read_context()
    assert "Original project info." not in content
    assert "Brand new content." in content


def test_apply_section_update_other_sections_preserved(tmp_synth):
    tmp_synth.apply_section_update("Project", "Changed.")
    content = tmp_synth.read_context()
    assert "## What TRACE does" in content
    assert "Original description." in content


def test_apply_section_update_heading_preserved(tmp_synth):
    tmp_synth.apply_section_update("Project", "New content.")
    content = tmp_synth.read_context()
    assert "## Project" in content
