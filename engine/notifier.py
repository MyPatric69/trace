"""Cross-platform notification helper for TRACE session health alerts.

Desktop notifications via platform-native tools (no external dependencies):
  macOS   – osascript (always available)
  Windows – win10toast (optional; silent fallback when not installed)
  Linux   – notify-send subprocess

Sound playback is also platform-native (afplay / winsound / paplay).

Never raises.  Errors are logged silently.
"""
from __future__ import annotations

import logging
import platform
import subprocess

_log = logging.getLogger(__name__)

_TITLES = {
    "warn":  "TRACE Warning",
    "reset": "TRACE Critical",
}
_MESSAGES = {
    "warn":  "Session at {tokens:,} tokens \u2013 prepare new thread",
    "reset": "Thread reset recommended ({tokens:,} tokens)",
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
    """Fire a cross-platform notification for a health-state escalation.

    Parameters
    ----------
    status  : "warn" | "reset"
    tokens  : effective session token count at the time of the alert
    project : registered project name
    config  : full trace config dict (reads ``notifications`` block)
    """
    if not project or project.lower() == "unknown":
        return

    cfg = config.get("notifications") or {}
    if not cfg.get("enabled", True):
        return

    if status not in _TITLES:
        return

    title   = _TITLES[status]
    message = _MESSAGES[status].format(tokens=tokens)
    body    = f"Project: {project}\n{message}"

    _send_notification(title, body)

    if cfg.get("sound", True):
        _play_sound(status, cfg)


def _send_notification(title: str, message: str) -> None:
    """Send a desktop notification using the platform-native mechanism."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(
                ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif system == "Windows":
            try:
                from win10toast import ToastNotifier
                ToastNotifier().show_toast(title, message, duration=8, threaded=True)
            except ImportError:
                pass  # win10toast is optional
        elif system == "Linux":
            subprocess.Popen(
                ["notify-send", title, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception as exc:
        _log.warning("Notification failed: %s", exc)


def _play_sound(status: str, cfg: dict) -> None:
    """Play a status-appropriate sound using platform-native APIs."""
    system = platform.system()
    try:
        if system == "Darwin":
            sound_name = cfg.get(_SOUND_KEYS[status], _SOUND_DEFAULTS[status])
            subprocess.Popen(
                ["afplay", f"/System/Library/Sounds/{sound_name}.aiff"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif system == "Windows":
            import winsound
            alias = "SystemAsterisk" if status == "warn" else "SystemExclamation"
            winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
        elif system == "Linux":
            sounds = {
                "warn":  ["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"],
                "reset": ["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
            }
            subprocess.Popen(
                sounds.get(status, sounds["warn"]),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception as exc:
        _log.warning("Sound failed: %s", exc)
