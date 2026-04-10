from datetime import date
from pathlib import Path

from engine.doc_synthesizer import DocSynthesizer
from engine.store import TraceStore

_CONFIG_PATH = Path(__file__).parents[2] / "trace_config.yaml"


def _store() -> TraceStore:
    store = TraceStore(str(_CONFIG_PATH))
    store.init_db()
    return store


def _synth(project_path: str) -> DocSynthesizer:
    return DocSynthesizer(project_path, config_path=str(_CONFIG_PATH))


def _baseline_hash(synth: DocSynthesizer) -> str:
    """Return the last-synced hash, falling back to the oldest commit if absent."""
    stored = synth.get_last_synced()
    if stored:
        return stored
    all_commits = list(synth.watcher.repo.iter_commits())
    return all_commits[-1].hexsha if all_commits else ""


def _recommendation(drift: dict) -> str:
    if not drift["is_stale"]:
        return "AI_CONTEXT.md is up to date"
    if not drift["doc_relevant_changes"]:
        return "Commits detected but no doc-relevant changes"
    return "AI_CONTEXT.md is stale – run update_context() to sync"


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

def check_drift(project_name: str) -> dict:
    store = _store()
    project = store.get_project(project_name)
    if project is None:
        return {"status": "error", "message": f"Project not found: {project_name}"}

    synth = _synth(project["path"])
    last_hash = _baseline_hash(synth)
    if not last_hash:
        return {"status": "error", "message": "No commits found in repository"}

    drift = synth.check_drift(last_hash)

    return {
        "status": "ok",
        "project": project_name,
        "is_stale": drift["is_stale"],
        "commits_behind": drift["commits_behind"],
        "doc_relevant_changes": drift["doc_relevant_changes"],
        "changed_files": drift["changed_files"],
        "current_hash": drift["current_hash"],
        "recommendation": _recommendation(drift),
    }


def update_context(project_name: str, dry_run: bool = False) -> dict:
    store = _store()
    project = store.get_project(project_name)
    if project is None:
        return {"status": "error", "message": f"Project not found: {project_name}"}

    synth = _synth(project["path"])
    last_hash = _baseline_hash(synth)
    if not last_hash:
        return {"status": "error", "message": "No commits found in repository"}

    drift = synth.check_drift(last_hash)
    prompt = synth.build_update_prompt(last_hash)

    if not drift["is_stale"]:
        return {
            "status": "up_to_date",
            "project": project_name,
            "commits_synced": 0,
            "files_affected": [],
            "sections_updated": [],
            "update_prompt": prompt,
        }

    if dry_run:
        return {
            "status": "dry_run",
            "project": project_name,
            "commits_synced": drift["commits_behind"],
            "files_affected": drift["changed_files"],
            "sections_updated": [],
            "update_prompt": prompt,
        }

    # Apply targeted section updates
    sections_updated: list[str] = []

    today = date.today().isoformat()
    last_updated = (
        f"{today} – Synced {drift['commits_behind']} commit(s) to {drift['current_hash']}"
    )
    if synth.apply_section_update("Last updated", last_updated):
        sections_updated.append("Last updated")

    engine_server = [
        f for f in drift["changed_files"]
        if f.startswith(("server/", "engine/"))
    ]
    if engine_server:
        files_str = ", ".join(engine_server[:5])
        if len(engine_server) > 5:
            files_str += f" (+{len(engine_server) - 5} more)"
        note = f"Review recent changes to: {files_str}"
        if synth.apply_section_update("Next steps", note):
            sections_updated.append("Next steps")

    synth.update_last_synced(drift["current_hash"])

    return {
        "status": "ok",
        "project": project_name,
        "commits_synced": drift["commits_behind"],
        "files_affected": drift["changed_files"],
        "sections_updated": sections_updated,
        "update_prompt": prompt,
    }
