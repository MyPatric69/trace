"""Tests for engine/handoff_builder.py and its integration with new_session()."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import yaml

from engine.handoff_builder import (
    _extract_section,
    _extract_test_command,
    _first_open_task,
    _recent_changed_files,
    _staleness_warning,
    build_handoff,
)
from engine.store import TraceStore
import server.tools.session as session_module

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

_BASE_PROMPT = """\
## Project

**Name:** TestProject – A minimal test project
**Status:** Phase 1 complete

**Last updated:** 2026-01-01"""

_CLAUDE_MD = """\
# CLAUDE.md

## Current Phase

**Phase 7 — Repo Bootstrapper (Epic 07).**
Test suite complete: 134 tests, all green.

## Runtime Rules

### Before major edits
- Read relevant docs first

### During edits
- Keep diffs small

## Dev Commands

```bash
npm run launch
npm run type-check
npm run dev
```

## Tech Stack

Next.js / TypeScript
"""

_MIN_CONFIG = {
    "trace": {"db_path": "trace.db", "version": "0.1.0"},
    "projects": [],
    "budgets": {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
    "session_health": {
        "warn_tokens": 80000,
        "critical_tokens": 150000,
        "claude_autocompact_approx": 180000,
    },
    "models": {
        "claude-sonnet-4-5": {"input_per_1k": 0.003, "output_per_1k": 0.015},
    },
}

_TEST_CONTEXT = """\
# AI_CONTEXT.md – TESTPROJECT

---

## Project

**Name:** TestProject – A minimal test project
**Status:** Phase 1 complete

---

## Architecture (current)

```
Layer A
    ↕
Layer B
```

---

## Key decisions

- **Local-heavy** – all heavy work done locally

---

## Next steps

- [ ] Next step one

---

## Last updated

2026-01-01
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "CLAUDE.md").write_text(_CLAUDE_MD, encoding="utf-8")
    (tmp_path / "AI_CONTEXT.md").write_text("# AI_CONTEXT.md\n\nsome content\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def repo_with_backlog(repo: Path) -> Path:
    backlog = repo / "backlog"
    backlog.mkdir()
    (backlog / "epic-01-foundation.md").write_text(
        "# Epic 01\n\n- [x] Done task\n- [ ] Pending task one\n- [ ] Pending task two\n",
        encoding="utf-8",
    )
    (backlog / "epic-02-context.md").write_text(
        "# Epic 02\n\n- [x] Already done\n- [ ] First open task in epic 02\n",
        encoding="utf-8",
    )
    return repo


def _make_session_env(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "trace_config.yaml"
    config_path.write_text(yaml.dump(_MIN_CONFIG), encoding="utf-8")
    (tmp_path / "AI_CONTEXT.md").write_text(_TEST_CONTEXT, encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text(_CLAUDE_MD, encoding="utf-8")

    store = TraceStore(str(config_path))
    store.init_db()
    store.add_project("testproject", str(tmp_path))

    monkeypatch.setattr(session_module, "_store", lambda: store)
    return {"store": store, "tmp_path": tmp_path}


# ---------------------------------------------------------------------------
# build_handoff – Current Phase extraction
# ---------------------------------------------------------------------------

def test_build_handoff_includes_current_phase(repo: Path):
    result = build_handoff(str(repo), _BASE_PROMPT)
    assert "## Current Phase" in result
    assert "Phase 7" in result


def test_build_handoff_current_phase_verbatim(repo: Path):
    result = build_handoff(str(repo), _BASE_PROMPT)
    assert "Test suite complete: 134 tests, all green." in result


def test_build_handoff_preserves_base_prompt(repo: Path):
    result = build_handoff(str(repo), _BASE_PROMPT)
    assert "## Project" in result
    assert "TestProject" in result


# ---------------------------------------------------------------------------
# build_handoff – open task from backlog
# ---------------------------------------------------------------------------

def test_build_handoff_finds_first_incomplete_checkbox(repo_with_backlog: Path):
    result = build_handoff(str(repo_with_backlog), _BASE_PROMPT)
    assert "## Open Task" in result
    # Highest-numbered epic is epic-02; its first open task should be used
    assert "First open task in epic 02" in result


def test_build_handoff_no_open_task_when_backlog_missing(repo: Path):
    result = build_handoff(str(repo), _BASE_PROMPT)
    assert "## Open Task" not in result


def test_first_open_task_picks_highest_epic(repo_with_backlog: Path):
    task = _first_open_task(repo_with_backlog / "backlog")
    assert "First open task in epic 02" in task


def test_first_open_task_returns_empty_when_no_incomplete(tmp_path: Path):
    backlog = tmp_path / "backlog"
    backlog.mkdir()
    (backlog / "epic-01.md").write_text("# Epic\n\n- [x] All done\n", encoding="utf-8")
    assert _first_open_task(backlog) == ""


def test_first_open_task_returns_empty_when_dir_missing(tmp_path: Path):
    assert _first_open_task(tmp_path / "backlog") == ""


# ---------------------------------------------------------------------------
# build_handoff – git diff file filtering
# ---------------------------------------------------------------------------

def test_build_handoff_includes_allowed_extensions(repo: Path, monkeypatch):
    fake_stdout = "app/foo.ts\napp/bar.py\nREADME.md\nconfig.yaml\napp/comp.tsx\n"
    monkeypatch.setattr(
        "engine.handoff_builder.subprocess.run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": fake_stdout})(),
    )
    result = build_handoff(str(repo), _BASE_PROMPT)
    assert "## Files to Read First" in result
    assert "app/foo.ts" in result
    assert "app/bar.py" in result
    assert "README.md" in result
    assert "config.yaml" in result
    assert "app/comp.tsx" in result


def test_build_handoff_excludes_disallowed_extensions(repo: Path, monkeypatch):
    fake_stdout = "app/style.css\napp/logo.png\napp/foo.ts\n"
    monkeypatch.setattr(
        "engine.handoff_builder.subprocess.run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": fake_stdout})(),
    )
    result = build_handoff(str(repo), _BASE_PROMPT)
    assert "app/style.css" not in result
    assert "app/logo.png" not in result
    assert "app/foo.ts" in result


def test_build_handoff_max_5_files(repo: Path, monkeypatch):
    fake_stdout = "\n".join(f"file{i}.py" for i in range(10))
    monkeypatch.setattr(
        "engine.handoff_builder.subprocess.run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": fake_stdout})(),
    )
    result = build_handoff(str(repo), _BASE_PROMPT)
    section_start = result.index("## Files to Read First")
    next_section = result.find("\n## ", section_start + 1)
    section = result[section_start: next_section if next_section != -1 else None]
    file_lines = [ln for ln in section.split("\n") if ln.strip().startswith("- ")]
    assert len(file_lines) <= 5


def test_build_handoff_deduplicates_files(repo: Path, monkeypatch):
    fake_stdout = "app/foo.py\napp/foo.py\napp/bar.py\n"
    monkeypatch.setattr(
        "engine.handoff_builder.subprocess.run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": fake_stdout})(),
    )
    result = build_handoff(str(repo), _BASE_PROMPT)
    assert result.count("app/foo.py") == 1


def test_build_handoff_skips_files_section_on_git_failure(repo: Path, monkeypatch):
    monkeypatch.setattr(
        "engine.handoff_builder.subprocess.run",
        lambda *a, **kw: type("R", (), {"returncode": 128, "stdout": ""})(),
    )
    result = build_handoff(str(repo), _BASE_PROMPT)
    assert "## Files to Read First" not in result


def test_recent_changed_files_returns_empty_on_exception(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("no git")
    monkeypatch.setattr("engine.handoff_builder.subprocess.run", _raise)
    assert _recent_changed_files("/any/path") == []


# ---------------------------------------------------------------------------
# build_handoff – Known Constraints and Test Command
# ---------------------------------------------------------------------------

def test_build_handoff_includes_known_constraints(repo: Path):
    result = build_handoff(str(repo), _BASE_PROMPT)
    assert "## Known Constraints" in result
    assert "Read relevant docs first" in result


def test_build_handoff_includes_test_command(repo: Path):
    result = build_handoff(str(repo), _BASE_PROMPT)
    assert "## Test Command" in result
    assert "type-check" in result


def test_extract_test_command_matches_pytest(tmp_path: Path):
    (tmp_path / "CLAUDE.md").write_text(
        "# C\n\n## Dev Commands\n\n```\npytest tests/ -v\nnpm run dev\n```\n",
        encoding="utf-8",
    )
    cmd = _extract_test_command(tmp_path / "CLAUDE.md")
    assert "pytest" in cmd


def test_extract_test_command_returns_empty_when_section_missing(tmp_path: Path):
    (tmp_path / "CLAUDE.md").write_text("# C\n\n## Other Section\n\nsome stuff\n", encoding="utf-8")
    assert _extract_test_command(tmp_path / "CLAUDE.md") == ""


def test_extract_test_command_single_line_returned_as_is(tmp_path: Path):
    (tmp_path / "CLAUDE.md").write_text(
        "# C\n\n## Dev Commands\n\n```\nnpm run dev\npytest tests/ -v\n```\n",
        encoding="utf-8",
    )
    cmd = _extract_test_command(tmp_path / "CLAUDE.md")
    assert cmd == "pytest tests/ -v"


def test_extract_test_command_joins_multiple_lines_with_and(tmp_path: Path):
    (tmp_path / "CLAUDE.md").write_text(
        "# C\n\n## Dev Commands\n\n```\nnpm test\nnpm run type-check\n```\n",
        encoding="utf-8",
    )
    cmd = _extract_test_command(tmp_path / "CLAUDE.md")
    assert cmd == "npm test && npm run type-check"


def test_extract_test_command_already_joined_not_doubled(tmp_path: Path):
    (tmp_path / "CLAUDE.md").write_text(
        "# C\n\n## Dev Commands\n\n```\nnpm test && npx tsc --noEmit\n```\n",
        encoding="utf-8",
    )
    cmd = _extract_test_command(tmp_path / "CLAUDE.md")
    assert cmd == "npm test && npx tsc --noEmit"
    assert cmd.count("&&") == 1


def test_extract_test_command_strips_code_fence_markers(tmp_path: Path):
    (tmp_path / "CLAUDE.md").write_text(
        "# C\n\n## Dev Commands\n\n```bash\npytest tests/\n```\n",
        encoding="utf-8",
    )
    cmd = _extract_test_command(tmp_path / "CLAUDE.md")
    assert "```" not in cmd
    assert "pytest" in cmd


def test_extract_test_command_truncates_at_200_chars(tmp_path: Path):
    long_cmd = "pytest " + "x" * 200
    (tmp_path / "CLAUDE.md").write_text(
        f"# C\n\n## Dev Commands\n\n```\n{long_cmd}\n```\n",
        encoding="utf-8",
    )
    cmd = _extract_test_command(tmp_path / "CLAUDE.md")
    assert len(cmd) <= 200
    assert cmd.endswith("...")


# ---------------------------------------------------------------------------
# build_handoff – graceful skipping of missing sections
# ---------------------------------------------------------------------------

def test_build_handoff_skips_current_phase_when_missing(tmp_path: Path):
    (tmp_path / "CLAUDE.md").write_text("# CLAUDE.md\n\n## Other Section\n\nsome content\n", encoding="utf-8")
    (tmp_path / "AI_CONTEXT.md").write_text("", encoding="utf-8")
    result = build_handoff(str(tmp_path), _BASE_PROMPT)
    assert "## Current Phase" not in result


def test_build_handoff_skips_all_when_no_claude_md(tmp_path: Path):
    (tmp_path / "AI_CONTEXT.md").write_text("", encoding="utf-8")
    result = build_handoff(str(tmp_path), _BASE_PROMPT)
    assert "## Current Phase" not in result
    assert "## Known Constraints" not in result
    assert "## Test Command" not in result
    assert _BASE_PROMPT.strip() in result


def test_build_handoff_returns_base_prompt_when_repo_invalid():
    result = build_handoff("/nonexistent/path/xyz_does_not_exist", _BASE_PROMPT)
    assert _BASE_PROMPT.strip() in result


# ---------------------------------------------------------------------------
# Staleness warning
# ---------------------------------------------------------------------------

def test_staleness_warning_when_context_older_than_2_days(tmp_path: Path):
    context = tmp_path / "AI_CONTEXT.md"
    context.write_text("# AI_CONTEXT.md\n", encoding="utf-8")
    old_time = time.time() - (5 * 24 * 3600)
    os.utime(context, (old_time, old_time))
    warning = _staleness_warning(tmp_path)
    assert "Warning" in warning
    assert "stale" in warning
    assert "5 days ago" in warning


def test_staleness_warning_absent_for_fresh_file(tmp_path: Path):
    context = tmp_path / "AI_CONTEXT.md"
    context.write_text("# AI_CONTEXT.md\n", encoding="utf-8")
    assert _staleness_warning(tmp_path) == ""


def test_staleness_warning_absent_when_no_context_file(tmp_path: Path):
    assert _staleness_warning(tmp_path) == ""


def test_staleness_warning_prepended_in_build_handoff(repo: Path):
    context = repo / "AI_CONTEXT.md"
    old_time = time.time() - (4 * 24 * 3600)
    os.utime(context, (old_time, old_time))
    result = build_handoff(str(repo), _BASE_PROMPT)
    assert result.startswith("> Warning:")
    assert "4 days ago" in result


def test_staleness_warning_not_prepended_when_fresh(repo: Path):
    result = build_handoff(str(repo), _BASE_PROMPT)
    assert not result.startswith("> Warning:")


# ---------------------------------------------------------------------------
# new_session() integration – enriched prompt
# ---------------------------------------------------------------------------

def test_new_session_dry_run_includes_current_phase(tmp_path: Path, monkeypatch):
    env = _make_session_env(tmp_path, monkeypatch)
    result = session_module.new_session("testproject", dry_run=True)
    assert result["status"] == "dry_run"
    assert "## Current Phase" in result["handoff_prompt"]
    assert "Phase 7" in result["handoff_prompt"]


def test_new_session_dry_run_includes_known_constraints(tmp_path: Path, monkeypatch):
    env = _make_session_env(tmp_path, monkeypatch)
    result = session_module.new_session("testproject", dry_run=True)
    assert "## Known Constraints" in result["handoff_prompt"]
    assert "Read relevant docs first" in result["handoff_prompt"]


def test_new_session_dry_run_includes_test_command(tmp_path: Path, monkeypatch):
    env = _make_session_env(tmp_path, monkeypatch)
    result = session_module.new_session("testproject", dry_run=True)
    assert "## Test Command" in result["handoff_prompt"]
    assert "type-check" in result["handoff_prompt"]


def test_new_session_falls_back_to_base_prompt_when_build_handoff_raises(
    tmp_path: Path, monkeypatch
):
    env = _make_session_env(tmp_path, monkeypatch)

    def _raise(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(session_module, "build_handoff", _raise)
    result = session_module.new_session("testproject", dry_run=True)
    assert result["status"] == "dry_run"
    assert isinstance(result["handoff_prompt"], str)
    assert len(result["handoff_prompt"]) > 0
