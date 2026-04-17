"""macOS notification helper for TRACE session health alerts.

Sends a native macOS notification (via osascript) and plays a sound
(via afplay) when session health crosses a threshold.  Non-blocking –
both subprocesses are spawned and immediately forgotten.

Never raises.  Skips silently on non-macOS systems or when disabled.
"""
from __future__ import annotations

import logging
import platform
import subprocess

_log = logging.getLogger(__name__)

_TITLES = {
    "warn":  "TRACE Warning",
    "reset": "TRACE Kritisch",
}
_MESSAGES = {
    "warn":  "Session bei {tokens:,} Tokens \u2013 neuen Thread vorbereiten",
    "reset": "Thread-Wechsel empfohlen ({tokens:,} Tokens)",
}
_SOUND_KEYS = {
    "warn":  "sound_warn",
    "reset": "sound_critical",
}
_SOUND_DEFAULTS = {
    "warn":  "Tink",
    "reset": "Funk",
}


def notify(status: str, tokens: int, project: str, config: dict) -> None:
    """Fire a macOS notification for a health-state escalation.

    Parameters
    ----------
    status  : "warn" | "reset"
    tokens  : effective session token count at the time of the alert
    project : registered project name
    config  : full trace config dict (reads ``notifications`` block)
    """
    if platform.system() != "Darwin":
        return

    notif_cfg = config.get("notifications") or {}
    if not notif_cfg.get("enabled", True):
        return

    if status not in _TITLES:
        return

    title    = _TITLES[status]
    message  = _MESSAGES[status].format(tokens=tokens)
    subtitle = f"Projekt: {project}"

    try:
        script = (
            f'display notification "{message}" '
            f'with title "{title}" '
            f'subtitle "{subtitle}"'
        )
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        _log.error("notifier: osascript failed: %s", exc)

    if notif_cfg.get("sound", True):
        sound_key  = _SOUND_KEYS[status]
        sound_name = notif_cfg.get(sound_key, _SOUND_DEFAULTS[status])
        sound_path = f"/System/Library/Sounds/{sound_name}.aiff"
        try:
            subprocess.Popen(
                ["afplay", sound_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            _log.error("notifier: afplay failed: %s", exc)
