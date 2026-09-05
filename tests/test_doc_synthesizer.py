"""Tests for engine/doc_synthesizer.py."""
import subprocess
from pathlib import Path

import git
import pytest

import engine.doc_synthesizer as doc_synthesizer_module
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


def _add_commit(tmp_path, repo, filename: str, content: str = "# x", msg: str = "update") -> str:
    """Write filename with content and commit it. Returns the new commit hexsha."""
    filepath = tmp_path / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    repo.index.add([filename])
    repo.index.commit(msg)
    return repo.head.commit.hexsha


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


# ---------------------------------------------------------------------------
# _auto_commit_context / update_if_stale auto-commit integration
# ---------------------------------------------------------------------------

def test_auto_commit_skipped_when_no_changes(tmp_synth):
    """No commit is made when AI_CONTEXT.md has no uncommitted diff."""
    repo = tmp_synth.watcher.repo
    commits_before = len(list(repo.iter_commits()))

    tmp_synth._auto_commit_context()

    assert len(list(repo.iter_commits())) == commits_before


def test_auto_commit_runs_when_context_has_changes(tmp_synth):
    """A dirty AI_CONTEXT.md is staged and committed with the expected message."""
    repo = tmp_synth.watcher.repo
    commits_before = len(list(repo.iter_commits()))

    (tmp_synth.project_path / "AI_CONTEXT.md").write_text("modified content\n", encoding="utf-8")
    tmp_synth._auto_commit_context()

    assert len(list(repo.iter_commits())) == commits_before + 1
    assert repo.head.commit.message.strip() == "chore(context): auto-sync AI_CONTEXT.md"
    # Working tree is clean again – nothing left uncommitted
    diff = subprocess.run(
        ["git", "diff", "--quiet", "AI_CONTEXT.md"],
        cwd=str(tmp_synth.project_path),
    )
    assert diff.returncode == 0


def test_auto_commit_only_commits_ai_context(tmp_synth):
    """Other dirty files in the working tree are left untouched/uncommitted."""
    repo = tmp_synth.watcher.repo
    (tmp_synth.project_path / "other.txt").write_text("unrelated change", encoding="utf-8")
    (tmp_synth.project_path / "AI_CONTEXT.md").write_text("modified content\n", encoding="utf-8")

    tmp_synth._auto_commit_context()

    assert repo.head.commit.message.strip() == "chore(context): auto-sync AI_CONTEXT.md"
    # other.txt must still be untracked – never staged or committed
    assert "other.txt" in repo.untracked_files


def test_auto_commit_failure_does_not_raise(tmp_synth, monkeypatch):
    """A git failure during add/commit is logged and swallowed, never raised."""
    (tmp_synth.project_path / "AI_CONTEXT.md").write_text("modified content\n", encoding="utf-8")

    real_run = doc_synthesizer_module.subprocess.run

    def _fake_run(cmd, **kwargs):
        if "commit" in cmd:
            raise RuntimeError("simulated git commit failure")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(doc_synthesizer_module.subprocess, "run", _fake_run)

    tmp_synth._auto_commit_context()  # must not raise


def test_auto_commit_diff_check_failure_does_not_raise(tmp_synth, monkeypatch):
    """A git failure during the diff check itself is also swallowed."""
    def _boom(*args, **kwargs):
        raise RuntimeError("git not found")

    monkeypatch.setattr(doc_synthesizer_module.subprocess, "run", _boom)

    tmp_synth._auto_commit_context()  # must not raise


def test_auto_commit_advances_trace_sync_to_include_itself(tmp_synth):
    """.trace_sync must be advanced to the auto-commit's own hash, not left
    pointing at the pre-auto-commit HEAD (which would make the very next
    drift check see the auto-commit itself as unsynced – see the recursion
    regression test below for why that matters)."""
    repo = tmp_synth.watcher.repo
    (tmp_synth.project_path / "AI_CONTEXT.md").write_text("modified content\n", encoding="utf-8")

    tmp_synth._auto_commit_context()

    assert tmp_synth.get_last_synced() == repo.head.commit.hexsha


def test_update_if_stale_reentrant_guard_env_var_short_circuits(tmp_path, tmp_synth, monkeypatch):
    """When the reentrancy guard env var is set, update_if_stale() must bail
    out immediately without touching AI_CONTEXT.md or the git history."""
    repo = tmp_synth.watcher.repo
    initial_hash = repo.head.commit.hexsha
    tmp_synth.update_last_synced(initial_hash)
    _add_commit(tmp_path, repo, "engine/module.py", msg="feat: new module")
    commits_before = len(list(repo.iter_commits()))

    monkeypatch.setenv(doc_synthesizer_module._SYNC_GUARD_ENV_VAR, "1")
    result = tmp_synth.update_if_stale()

    assert result is False
    assert len(list(repo.iter_commits())) == commits_before


def test_update_if_stale_does_not_recurse_after_auto_commit(tmp_path, tmp_synth):
    """Regression test for the infinite-loop bug: the auto-commit created by
    update_if_stale() re-fires this repo's own post-commit hook, which calls
    update_if_stale() again. Because AI_CONTEXT.md is itself a doc-relevant
    (.md) file, a naive implementation sees drift again and recurses forever.
    A second call – simulating that nested hook invocation – must be a no-op."""
    repo = tmp_synth.watcher.repo
    initial_hash = repo.head.commit.hexsha
    tmp_synth.update_last_synced(initial_hash)
    _add_commit(tmp_path, repo, "engine/module.py", msg="feat: new module")

    result1 = tmp_synth.update_if_stale()
    assert result1 is True
    commits_after_first_sync = len(list(repo.iter_commits()))

    # Simulate the auto-commit's own post-commit hook invoking update_if_stale() again
    result2 = tmp_synth.update_if_stale()

    assert result2 is False
    assert len(list(repo.iter_commits())) == commits_after_first_sync


def test_update_if_stale_auto_commits_context_when_stale(tmp_path, tmp_synth):
    """The full update_if_stale() flow leaves no uncommitted AI_CONTEXT.md diff."""
    repo = tmp_synth.watcher.repo
    initial_hash = repo.head.commit.hexsha
    tmp_synth.update_last_synced(initial_hash)

    # Doc-relevant commit so update_if_stale() actually rewrites AI_CONTEXT.md
    _add_commit(tmp_path, repo, "engine/module.py", msg="feat: new module")

    commits_before = len(list(repo.iter_commits()))
    result = tmp_synth.update_if_stale()

    assert result is True
    assert len(list(repo.iter_commits())) == commits_before + 1
    assert repo.head.commit.message.strip() == "chore(context): auto-sync AI_CONTEXT.md"

    diff = subprocess.run(
        ["git", "diff", "--quiet", "AI_CONTEXT.md"],
        cwd=str(tmp_synth.project_path),
    )
    assert diff.returncode == 0
