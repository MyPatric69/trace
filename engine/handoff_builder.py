"""Enriches a handoff prompt with project-specific context.

Pure local extraction – no LLM calls, no network.
Reads CLAUDE.md, backlog/, and recent git history from repo_path.
All failures are caught and silently skipped so the base_prompt is
always returned even when the repo has none of the optional files.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

_ALLOWED_EXTS = frozenset({".ts", ".tsx", ".md", ".py", ".yaml"})
_TEST_RE = re.compile(
    r"\b(pytest|vitest|jest|type.?check|tsc|npm\s+test|test|check|verify)\b",
    re.IGNORECASE,
)
_MAX_TEST_CMD = 200


def build_handoff(repo_path: str, base_prompt: str) -> str:
    """Enrich base_prompt with sections derived from the repo.

    Sections appended (in order, each omitted silently when unavailable):
        ## Current Phase     – from CLAUDE.md ## Current Phase
        ## Open Task         – first incomplete checkbox in backlog/epic-*.md
        ## Files to Read First – from git diff --name-only HEAD~3
        ## Known Constraints – from CLAUDE.md ## Runtime Rules
        ## Test Command      – test/type-check line from CLAUDE.md ## Dev Commands

    A staleness warning is prepended when AI_CONTEXT.md mtime > 2 days.
    Falls back to base_prompt unchanged if an unexpected exception occurs.
    """
    root = Path(repo_path)
    parts: list[str] = []

    warning = _staleness_warning(root)
    if warning:
        parts.append(warning)

    parts.append(base_prompt.strip())

    phase = _extract_section(root / "CLAUDE.md", "Current Phase")
    if phase:
        parts.append(f"## Current Phase\n\n{phase}")

    task = _first_open_task(root / "backlog")
    if task:
        parts.append(f"## Open Task\n\n{task}")

    files = _recent_changed_files(str(root))
    if files:
        file_lines = "\n".join(f"- {f}" for f in files)
        parts.append(f"## Files to Read First\n\n{file_lines}")

    constraints = _extract_section(root / "CLAUDE.md", "Runtime Rules")
    if constraints:
        parts.append(f"## Known Constraints\n\n{constraints}")

    test_cmd = _extract_test_command(root / "CLAUDE.md")
    if test_cmd:
        parts.append(f"## Test Command\n\n{test_cmd}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _staleness_warning(root: Path) -> str:
    """Return a blockquote warning if AI_CONTEXT.md is older than 2 days."""
    context_file = root / "AI_CONTEXT.md"
    if not context_file.exists():
        return ""
    try:
        mtime = datetime.fromtimestamp(context_file.stat().st_mtime, tz=timezone.utc)
        age_days = (datetime.now(tz=timezone.utc) - mtime).days
        if age_days > 2:
            return (
                f"> Warning: AI_CONTEXT.md last updated {age_days} days ago – may be stale.\n"
                "> Run update_context to refresh before starting work."
            )
    except OSError:
        pass
    return ""


def _extract_section(path: Path, heading: str) -> str:
    """Return the body of '## heading' from path. Empty string if not found."""
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").split("\n")
    except OSError:
        return ""
    target = f"## {heading}"
    start: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == target or stripped.startswith(f"{target} "):
            start = i + 1
            break
    if start is None:
        return ""
    body: list[str] = []
    for line in lines[start:]:
        if line.startswith("## ") or line.strip() == "---":
            break
        body.append(line)
    return "\n".join(body).strip()


def _first_open_task(backlog_dir: Path) -> str:
    """Return the first '- [ ] ...' line from the highest-numbered epic file."""
    if not backlog_dir.is_dir():
        return ""
    epics = sorted(backlog_dir.glob("epic-*.md"), reverse=True)
    for epic_file in epics:
        try:
            for line in epic_file.read_text(encoding="utf-8").split("\n"):
                stripped = line.strip()
                if stripped.startswith("- [ ]"):
                    return stripped
        except OSError:
            continue
    return ""


def _recent_changed_files(repo_path: str) -> list[str]:
    """Return up to 5 recently changed files (allowed extensions) via git diff HEAD~3."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo_path, "diff", "--name-only", "HEAD~3"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return []
        seen: set[str] = set()
        files: list[str] = []
        for raw in proc.stdout.splitlines():
            f = raw.strip()
            if f and Path(f).suffix in _ALLOWED_EXTS and f not in seen:
                seen.add(f)
                files.append(f)
                if len(files) == 5:
                    break
        return files
    except Exception:
        return []


def _extract_test_command(claude_path: Path) -> str:
    """Extract all test/type-check command lines from ## Dev Commands.

    All matching lines are joined with ' && '.
    Code fence markers (``` lines) and comment-only lines (# ...) are skipped.
    Result is truncated to 200 chars with '...' suffix.
    """
    section = _extract_section(claude_path, "Dev Commands")
    if not section:
        return ""

    matches: list[str] = []
    for line in section.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("```") or stripped.startswith("#"):
            continue
        if _TEST_RE.search(stripped):
            matches.append(stripped)

    if not matches:
        return ""

    result = matches[0] if len(matches) == 1 else " && ".join(matches)
    if len(result) > _MAX_TEST_CMD:
        result = result[: _MAX_TEST_CMD - 3] + "..."
    return result
