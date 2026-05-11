"""Unified config loader for TRACE.

Two-file layout:
  System config  → {repo_root}/trace_config.yaml   (models, prices; never written at runtime)
  User config    → ~/.trace/user_config.yaml        (thresholds, notifications, budget, etc.)

TraceConfig merges both into a single dict so all existing callers that do
``store.config.get("session_health")`` continue to work unchanged.

On first access, if user_config.yaml does not exist, user settings are
migrated from the legacy ~/.trace/trace_config.yaml (if present) and
written to the new file.  The legacy file is left untouched.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

TRACE_HOME = Path.home() / ".trace"

_log = logging.getLogger(__name__)

# Top-level keys that belong in user config (user can change these)
_USER_KEYS: frozenset[str] = frozenset({
    "session_health",
    "notifications",
    "budgets",
    "comparison",
    "mcp_servers",
})

_USER_DEFAULTS: dict = {
    "session_health": {
        "warn_tokens": 120_000,
        "critical_tokens": 200_000,
        "warn_context_pct": 60,
        "critical_context_pct": 85,
    },
    "notifications":  {"enabled": True, "sound": True},
    "budgets":        {"default_monthly_usd": 125.0, "alert_threshold_pct": 80},
    "comparison":     {"baseline_model": "claude-sonnet-4-6"},
    "mcp_servers":    [],
}


class TraceConfig:
    """Loads, merges, and persists TRACE configuration.

    Parameters
    ----------
    system_config_path:
        Path to the read-only system config (repo-local ``trace_config.yaml``).
        Defaults to ``{repo_root}/trace_config.yaml``.
    user_config_path:
        Path to the writable user config. Defaults to
        ``~/.trace/user_config.yaml``. Created with migration on first access.
    _legacy_path:
        Override for the legacy ``~/.trace/trace_config.yaml`` used as the
        migration source.  Intended for tests only.
    """

    _REPO_ROOT = Path(__file__).parents[1]
    USER_CONFIG_PATH = TRACE_HOME / "user_config.yaml"

    def __init__(
        self,
        system_config_path: Path | str | None = None,
        user_config_path: Path | str | None = None,
        _legacy_path: Path | str | None = None,
    ) -> None:
        self._system_path: Path = (
            Path(system_config_path)
            if system_config_path is not None
            else self._REPO_ROOT / "trace_config.yaml"
        )
        self._user_path: Path = (
            Path(user_config_path)
            if user_config_path is not None
            else TRACE_HOME / "user_config.yaml"
        )
        self._legacy_path: Path = (
            Path(_legacy_path)
            if _legacy_path is not None
            else TRACE_HOME / "trace_config.yaml"
        )

        self.system_config: dict = self._load_system_config()
        self._ensure_user_config()
        self.user_config: dict = self._load_user_config()
        self.merged: dict = self._build_merged()

    @classmethod
    def default(cls) -> "TraceConfig":
        """Standard entry point – uses repo system config and ~/.trace/user_config.yaml."""
        return cls()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_system_config(self) -> dict:
        if self._system_path.exists():
            try:
                with open(self._system_path, encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception as exc:
                _log.warning("TraceConfig: failed to load system config %s: %s", self._system_path, exc)
        # Fallback: legacy ~/.trace/trace_config.yaml (covers fresh-checkout scenarios)
        if self._legacy_path.exists():
            try:
                with open(self._legacy_path, encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                pass
        return {}

    def _ensure_user_config(self) -> None:
        """Create user_config.yaml if absent, migrating from legacy trace_config.yaml."""
        if self._user_path.exists():
            return
        self._user_path.parent.mkdir(parents=True, exist_ok=True)
        user_data: dict = {}

        if self._legacy_path.exists():
            try:
                with open(self._legacy_path, encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
                for key in _USER_KEYS:
                    if key in existing:
                        user_data[key] = existing[key]
            except Exception as exc:
                _log.warning("TraceConfig: migration from %s failed: %s", self._legacy_path, exc)

        for key, default in _USER_DEFAULTS.items():
            user_data.setdefault(key, default)

        self._write_user_config(user_data)

    def _load_user_config(self) -> dict:
        try:
            with open(self._user_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as exc:
            _log.warning("TraceConfig: failed to load user config %s: %s", self._user_path, exc)
            return {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
                    for k, v in _USER_DEFAULTS.items()}

    # ------------------------------------------------------------------
    # Merging
    # ------------------------------------------------------------------

    def _build_merged(self) -> dict:
        """System config base, with user keys always sourced from user_config or defaults."""
        merged = dict(self.system_config)
        for key in _USER_KEYS:
            # Always assign user keys so system config never leaks user settings
            merged[key] = self.user_config.get(key, _USER_DEFAULTS.get(key))
        return merged

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_model_price(self, model: str) -> dict | None:
        """Return price dict for *model*; falls back to prefix matching."""
        models = self.system_config.get("models", {})
        return models.get(model) or next(
            (v for k, v in models.items() if model.startswith(k)), None
        )

    def get_user_setting(self, key: str, default=None):
        """Return a top-level user setting by key."""
        return self.user_config.get(key, default)

    def save_user_setting(self, key: str, value) -> None:
        """Persist a single top-level user setting and rebuild merged."""
        self.user_config[key] = value
        self.save_user_config()

    def save_user_config(self) -> None:
        """Write current user_config dict to disk and rebuild merged."""
        self._write_user_config(self.user_config)
        self.merged = self._build_merged()

    def _write_user_config(self, data: dict) -> None:
        text = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        self._user_path.write_text(text, encoding="utf-8")
