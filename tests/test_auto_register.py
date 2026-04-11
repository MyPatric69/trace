"""Tests for engine/auto_register.py – register_if_unknown()."""
import pytest
from pathlib import Path

from engine.store import TraceStore
import engine.auto_register as ar_module
from engine.auto_register import register_if_unknown, _detect_project_name


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ar_env(tmp_path, tmp_store: TraceStore, monkeypatch):
    """Inject tmp_store into the auto_register module."""
    monkeypatch.setattr(ar_module, "_store", lambda: tmp_store)
    return tmp_path, tmp_store


# ---------------------------------------------------------------------------
# register_if_unknown – structure
# ---------------------------------------------------------------------------

def test_register_if_unknown_returns_correct_structure(ar_env):
    tmp_path, _ = ar_env
    result = register_if_unknown(str(tmp_path))
    for key in ("registered", "project_name", "project_path", "message"):
        assert key in result, f"missing key: {key}"


def test_register_if_unknown_registered_is_bool(ar_env):
    tmp_path, _ = ar_env
    result = register_if_unknown(str(tmp_path))
    assert isinstance(result["registered"], bool)


def test_register_if_unknown_message_is_str(ar_env):
    tmp_path, _ = ar_env
    result = register_if_unknown(str(tmp_path))
    assert isinstance(result["message"], str)
    assert len(result["message"]) > 0


# ---------------------------------------------------------------------------
# register_if_unknown – registration behaviour
# ---------------------------------------------------------------------------

def test_register_if_unknown_registers_new_project(ar_env):
    tmp_path, store = ar_env
    result = register_if_unknown(str(tmp_path))
    assert result["registered"] is True
    assert store.get_project(result["project_name"]) is not None


def test_register_if_unknown_returns_resolved_path(ar_env):
    tmp_path, _ = ar_env
    result = register_if_unknown(str(tmp_path))
    assert result["project_path"] == str(tmp_path.resolve())


def test_register_if_unknown_skips_existing_project(ar_env, monkeypatch):
    tmp_path, store = ar_env
    name = tmp_path.name
    monkeypatch.setattr(ar_module, "_detect_project_name", lambda p: name)
    store.add_project(name, str(tmp_path))

    result = register_if_unknown(str(tmp_path))

    assert result["registered"] is False
    assert result["project_name"] == name
    # Still only one project in store
    assert len(store.list_projects()) == 1


def test_register_if_unknown_idempotent_second_call(ar_env, monkeypatch):
    tmp_path, store = ar_env
    name = tmp_path.name
    monkeypatch.setattr(ar_module, "_detect_project_name", lambda p: name)

    result1 = register_if_unknown(str(tmp_path))
    result2 = register_if_unknown(str(tmp_path))

    assert result1["registered"] is True
    assert result2["registered"] is False
    assert len(store.list_projects()) == 1


# ---------------------------------------------------------------------------
# _detect_project_name – directory name fallback
# ---------------------------------------------------------------------------

def test_detect_project_name_returns_string(tmp_path):
    name = _detect_project_name(str(tmp_path))
    assert isinstance(name, str)
    assert len(name) > 0


def test_detect_project_name_falls_back_to_dir_name(tmp_path):
    """tmp_path is not a git repo with a remote → must use directory name."""
    name = _detect_project_name(str(tmp_path))
    assert name == tmp_path.name


def test_detect_project_name_strips_git_suffix(monkeypatch):
    """URL ending in .git is stripped."""
    import subprocess

    class _FakeResult:
        returncode = 0
        stdout = "https://github.com/user/my-repo.git\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeResult())
    name = _detect_project_name("/some/path")
    assert name == "my-repo"


def test_detect_project_name_handles_ssh_url(monkeypatch):
    """SSH remote URL like git@github.com:user/my-repo.git."""
    import subprocess

    class _FakeResult:
        returncode = 0
        stdout = "git@github.com:user/my-repo.git\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeResult())
    name = _detect_project_name("/some/path")
    assert name == "my-repo"
