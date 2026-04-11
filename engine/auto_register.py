"""Auto-register a git project in the central TRACE database.

Called by the post-commit hook on every commit. Safe to call multiple times –
skips registration if the project is already known.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[1]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.store import TraceStore  # noqa: E402 (after path setup)


def _store() -> TraceStore:
    store = TraceStore.default()
    store.init_db()
    return store


def _detect_project_name(project_path: str) -> str:
    """Detect project name from git remote origin URL, falling back to directory name."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            url = result.stdout.strip().rstrip("/")
            name = url.split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]
            if name:
                return name
    except Exception:
        pass
    return Path(project_path).resolve().name


def register_if_unknown(project_path: str) -> dict:
    """Register project in ~/.trace/trace.db if not already present.

    Returns:
        dict with keys: registered (bool), project_name, project_path, message
    """
    resolved = str(Path(project_path).resolve())
    store = _store()
    name = _detect_project_name(resolved)

    if store.get_project(name) is not None:
        return {
            "registered": False,
            "project_name": name,
            "project_path": resolved,
            "message": f"Project '{name}' already registered.",
        }

    try:
        store.add_project(name, resolved)
    except Exception as exc:
        return {
            "registered": False,
            "project_name": name,
            "project_path": resolved,
            "message": f"Registration failed: {exc}",
        }

    return {
        "registered": True,
        "project_name": name,
        "project_path": resolved,
        "message": f"Project '{name}' registered at {resolved}.",
    }


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = register_if_unknown(path)
    print(result["message"])
