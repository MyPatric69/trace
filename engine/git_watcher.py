from __future__ import annotations

from pathlib import Path

from git import InvalidGitRepositoryError, Repo


class GitWatcher:
    """Detects git commits and extracts structured info for doc synthesis."""

    _EMPTY_COMMIT: dict = {
        "hash": "",
        "message": "",
        "author": "",
        "timestamp": "",
        "files_changed": [],
        "diff_summary": "no commits",
    }

    def __init__(self, project_path: str) -> None:
        path = Path(project_path).resolve()
        try:
            self.repo = Repo(str(path), search_parent_directories=True)
        except InvalidGitRepositoryError:
            raise ValueError(f"Not a git repository: {project_path}")
        self.project_path = path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _commit_to_dict(self, commit) -> dict:
        files_changed = list(commit.stats.files.keys())
        total = commit.stats.total
        n_files = total.get("files", 0)
        ins = total.get("insertions", 0)
        dels = total.get("deletions", 0)

        if n_files == 0:
            diff_summary = "no changes"
        else:
            top = files_changed[:3]
            label = ", ".join(top)
            if len(files_changed) > 3:
                label += f" (+{len(files_changed) - 3} more)"
            diff_summary = (
                f"{n_files} file{'s' if n_files != 1 else ''} changed "
                f"(+{ins}/-{dels}): {label}"
            )

        return {
            "hash": commit.hexsha[:7],
            "message": commit.message.strip(),
            "author": commit.author.name,
            "timestamp": commit.authored_datetime.isoformat(),
            "files_changed": files_changed,
            "diff_summary": diff_summary,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_last_commit(self) -> dict:
        """Return structured info about the most recent commit."""
        try:
            return self._commit_to_dict(self.repo.head.commit)
        except Exception:
            return dict(self._EMPTY_COMMIT)

    def get_commits_since(self, since_hash: str) -> list[dict]:
        """Return all commits that came after since_hash (since_hash excluded)."""
        try:
            commits = list(self.repo.iter_commits(f"{since_hash}..HEAD"))
            return [self._commit_to_dict(c) for c in commits]
        except Exception:
            return []

    def get_changed_files(self, since_hash: str | None = None) -> list[str]:
        """Return files changed since since_hash, or just the last commit if None."""
        try:
            if since_hash is None:
                return list(self.repo.head.commit.stats.files.keys())
            commits = list(self.repo.iter_commits(f"{since_hash}..HEAD"))
            files: set[str] = set()
            for commit in commits:
                files.update(commit.stats.files.keys())
            return sorted(files)
        except Exception:
            return []

    def is_doc_relevant(self, file_path: str) -> bool:
        """Return True if this file should trigger an AI_CONTEXT.md update."""
        path = Path(file_path)
        if path.suffix in {".py", ".md"}:
            return True
        if path.name == "trace_config.yaml":
            return True
        if path.parts and path.parts[0] in {"server", "engine"}:
            return True
        return False
