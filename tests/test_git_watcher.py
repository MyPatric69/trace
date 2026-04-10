"""Tests for engine/git_watcher.py – uses the TRACE repo itself as the test fixture."""
from pathlib import Path

import pytest

from engine.git_watcher import GitWatcher

# Project root – two levels up from tests/
REPO_ROOT = str(Path(__file__).parents[1])


@pytest.fixture
def watcher() -> GitWatcher:
    return GitWatcher(REPO_ROOT)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

def test_init_valid_repo():
    gw = GitWatcher(REPO_ROOT)
    assert gw.project_path == Path(REPO_ROOT).resolve()


def test_init_invalid_path(tmp_path):
    with pytest.raises(ValueError, match="Not a git repository"):
        GitWatcher(str(tmp_path))


# ---------------------------------------------------------------------------
# get_last_commit – structure and types
# ---------------------------------------------------------------------------

def test_get_last_commit_returns_all_keys(watcher):
    commit = watcher.get_last_commit()
    expected_keys = {"hash", "message", "author", "timestamp", "files_changed", "diff_summary"}
    assert expected_keys == set(commit.keys())


def test_get_last_commit_hash_is_seven_chars(watcher):
    commit = watcher.get_last_commit()
    assert len(commit["hash"]) == 7


def test_get_last_commit_files_changed_is_list(watcher):
    commit = watcher.get_last_commit()
    assert isinstance(commit["files_changed"], list)


def test_get_last_commit_message_is_non_empty_string(watcher):
    commit = watcher.get_last_commit()
    assert isinstance(commit["message"], str)
    assert len(commit["message"]) > 0


def test_get_last_commit_diff_summary_is_string(watcher):
    commit = watcher.get_last_commit()
    assert isinstance(commit["diff_summary"], str)
    assert len(commit["diff_summary"]) > 0


def test_get_last_commit_timestamp_is_iso_format(watcher):
    from datetime import datetime
    commit = watcher.get_last_commit()
    # Should parse without error
    dt = datetime.fromisoformat(commit["timestamp"])
    assert dt.year > 2000


# ---------------------------------------------------------------------------
# get_commits_since
# ---------------------------------------------------------------------------

def test_get_commits_since_empty_for_current_head(watcher):
    last = watcher.get_last_commit()
    result = watcher.get_commits_since(last["hash"])
    assert result == []


def test_get_commits_since_returns_commits_after_root(watcher):
    all_commits = list(watcher.repo.iter_commits())
    if len(all_commits) < 2:
        pytest.skip("Need at least 2 commits")
    root = all_commits[-1]
    result = watcher.get_commits_since(root.hexsha)
    assert isinstance(result, list)
    assert len(result) >= 1
    # Root commit itself must not be in the result
    hashes = {c["hash"] for c in result}
    assert root.hexsha[:7] not in hashes


def test_get_commits_since_invalid_hash_returns_empty(watcher):
    result = watcher.get_commits_since("0000000")
    assert result == []


def test_get_commits_since_each_has_correct_keys(watcher):
    all_commits = list(watcher.repo.iter_commits())
    if len(all_commits) < 2:
        pytest.skip("Need at least 2 commits")
    root = all_commits[-1]
    result = watcher.get_commits_since(root.hexsha)
    expected_keys = {"hash", "message", "author", "timestamp", "files_changed", "diff_summary"}
    for commit in result:
        assert expected_keys == set(commit.keys())


# ---------------------------------------------------------------------------
# get_changed_files
# ---------------------------------------------------------------------------

def test_get_changed_files_no_arg_returns_list(watcher):
    result = watcher.get_changed_files()
    assert isinstance(result, list)


def test_get_changed_files_with_since_hash_returns_list(watcher):
    all_commits = list(watcher.repo.iter_commits())
    if len(all_commits) < 2:
        pytest.skip("Need at least 2 commits")
    root = all_commits[-1]
    result = watcher.get_changed_files(since_hash=root.hexsha)
    assert isinstance(result, list)
    assert len(result) >= 1


def test_get_changed_files_invalid_hash_returns_empty(watcher):
    assert watcher.get_changed_files(since_hash="0000000") == []


# ---------------------------------------------------------------------------
# is_doc_relevant
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    # Python files → relevant
    ("engine/store.py", True),
    ("server/main.py", True),
    ("tests/test_store.py", True),
    ("any_script.py", True),
    # Markdown files → relevant
    ("AI_CONTEXT.md", True),
    ("VISION.md", True),
    ("docs/notes.md", True),
    # Config file → relevant
    ("trace_config.yaml", True),
    # server/ and engine/ prefixed paths → relevant (even non-py/md)
    ("server/tools/costs.py", True),
    ("engine/git_watcher.py", True),
    # Irrelevant files
    ("trace.db", False),
    (".gitignore", False),
    ("LICENSE", False),
    ("data/export.csv", False),
    ("other_config.yaml", False),
])
def test_is_doc_relevant(watcher, path, expected):
    assert watcher.is_doc_relevant(path) is expected
