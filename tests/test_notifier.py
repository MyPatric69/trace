"""Tests for engine/notifier.py and live_tracker.py notification integration."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import yaml

import engine.live_tracker as lt_module
from engine.live_tracker import LiveTracker
from engine.store import TraceStore


# ---------------------------------------------------------------------------
# Shared config fixtures
# ---------------------------------------------------------------------------

_ENABLED_CONFIG = {
    "notifications": {"enabled": True, "sound": True, "sound_warn": "Tink", "sound_critical": "Funk"},
}
_DISABLED_CONFIG = {
    "notifications": {"enabled": False, "sound": True},
}
_NO_SOUND_CONFIG = {
    "notifications": {"enabled": True, "sound": False, "sound_warn": "Tink", "sound_critical": "Funk"},
}

_MODEL_PRICES = {
    "claude-sonnet-4-6": {
        "input_per_1k": 0.003, "output_per_1k": 0.015,
        "cache_creation_per_1k": 0.00375, "cache_read_per_1k": 0.0003,
    },
}

_SESSION_HEALTH_CFG = {"warn_tokens": 1_000, "critical_tokens": 2_000}


# ---------------------------------------------------------------------------
# engine/notifier.py – disabled / unknown status
# ---------------------------------------------------------------------------

class TestNotifyDisabled:
    def test_does_nothing_when_enabled_false(self):
        from engine.notifier import notify
        with patch("engine.notifier._send_notification") as mock_send, \
             patch("engine.notifier._play_sound") as mock_sound:
            notify("warn", 90_000, "myproject", _DISABLED_CONFIG)
        mock_send.assert_not_called()
        mock_sound.assert_not_called()

    def test_does_nothing_when_notifications_block_missing(self):
        """Empty config: enabled defaults True – must not raise regardless."""
        from engine.notifier import notify
        with patch("engine.notifier._send_notification"), \
             patch("engine.notifier._play_sound"):
            notify("warn", 90_000, "myproject", {})
        # No assertion – just verifying no exception

    def test_unknown_status_does_nothing(self):
        from engine.notifier import notify
        with patch("engine.notifier._send_notification") as mock_send, \
             patch("engine.notifier._play_sound") as mock_sound:
            notify("ok", 90_000, "myproject", _ENABLED_CONFIG)
        mock_send.assert_not_called()
        mock_sound.assert_not_called()

    def test_sound_skipped_when_sound_false(self):
        from engine.notifier import notify
        with patch("engine.notifier._send_notification") as mock_send, \
             patch("engine.notifier._play_sound") as mock_sound:
            notify("warn", 90_000, "proj", _NO_SOUND_CONFIG)
        mock_send.assert_called_once()
        mock_sound.assert_not_called()

    def test_notification_always_fires_when_enabled(self):
        from engine.notifier import notify
        with patch("engine.notifier._send_notification") as mock_send, \
             patch("engine.notifier._play_sound"):
            notify("warn", 90_000, "proj", _ENABLED_CONFIG)
            notify("reset", 160_000, "proj", _ENABLED_CONFIG)
        assert mock_send.call_count == 2


# ---------------------------------------------------------------------------
# engine/notifier.notify() – unknown / empty project suppression
# ---------------------------------------------------------------------------

class TestNotifyUnknownProject:
    def test_returns_early_for_unknown_lowercase(self):
        from engine.notifier import notify
        with patch("engine.notifier._send_notification") as mock_send, \
             patch("engine.notifier._play_sound") as mock_sound:
            notify("warn", 90_000, "unknown", _ENABLED_CONFIG)
        mock_send.assert_not_called()
        mock_sound.assert_not_called()

    def test_returns_early_for_unknown_titlecase(self):
        from engine.notifier import notify
        with patch("engine.notifier._send_notification") as mock_send, \
             patch("engine.notifier._play_sound") as mock_sound:
            notify("warn", 90_000, "Unknown", _ENABLED_CONFIG)
        mock_send.assert_not_called()
        mock_sound.assert_not_called()

    def test_returns_early_for_empty_string(self):
        from engine.notifier import notify
        with patch("engine.notifier._send_notification") as mock_send, \
             patch("engine.notifier._play_sound") as mock_sound:
            notify("warn", 90_000, "", _ENABLED_CONFIG)
        mock_send.assert_not_called()
        mock_sound.assert_not_called()

    def test_returns_early_for_none_project(self):
        from engine.notifier import notify
        with patch("engine.notifier._send_notification") as mock_send, \
             patch("engine.notifier._play_sound") as mock_sound:
            notify("warn", 90_000, None, _ENABLED_CONFIG)
        mock_send.assert_not_called()
        mock_sound.assert_not_called()

    def test_fires_for_real_project(self):
        from engine.notifier import notify
        with patch("engine.notifier._send_notification") as mock_send, \
             patch("engine.notifier._play_sound"):
            notify("warn", 90_000, "my-project", _ENABLED_CONFIG)
        mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# engine/notifier.notify() – English message text
# ---------------------------------------------------------------------------

class TestNotifyEnglishText:
    def test_warn_body_contains_project_label_english(self):
        from engine.notifier import notify
        captured: list[tuple] = []
        with patch("engine.notifier._send_notification",
                   side_effect=lambda t, m: captured.append((t, m))), \
             patch("engine.notifier._play_sound"):
            notify("warn", 90_000, "my-project", _ENABLED_CONFIG)
        _, body = captured[0]
        assert body.startswith("Project:")

    def test_warn_message_is_english(self):
        from engine.notifier import notify
        captured: list[tuple] = []
        with patch("engine.notifier._send_notification",
                   side_effect=lambda t, m: captured.append((t, m))), \
             patch("engine.notifier._play_sound"):
            notify("warn", 90_000, "proj", _ENABLED_CONFIG)
        _, body = captured[0]
        assert "prepare new thread" in body

    def test_reset_message_is_english(self):
        from engine.notifier import notify
        captured: list[tuple] = []
        with patch("engine.notifier._send_notification",
                   side_effect=lambda t, m: captured.append((t, m))), \
             patch("engine.notifier._play_sound"):
            notify("reset", 160_000, "proj", _ENABLED_CONFIG)
        _, body = captured[0]
        assert "Thread reset recommended" in body

    def test_body_contains_token_count_english_format(self):
        from engine.notifier import notify
        captured: list[tuple] = []
        with patch("engine.notifier._send_notification",
                   side_effect=lambda t, m: captured.append((t, m))), \
             patch("engine.notifier._play_sound"):
            notify("warn", 90_000, "proj", _ENABLED_CONFIG)
        _, body = captured[0]
        assert "90,000" in body


# ---------------------------------------------------------------------------
# engine/notifier._send_notification() – platform-native dispatch
# ---------------------------------------------------------------------------

class TestNotifySend:
    """_send_notification() uses the right tool per platform."""

    # ── macOS ──────────────────────────────────────────────────────────────

    def test_calls_osascript_on_darwin(self):
        from engine.notifier import _send_notification
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            _send_notification("TRACE Warning", "Projekt: proj\nsome message")
        assert mock_popen.call_count == 1
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "osascript"

    def test_darwin_osascript_contains_title(self):
        from engine.notifier import _send_notification
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            _send_notification("TRACE Warning", "Projekt: myproject\nbody")
        script = mock_popen.call_args[0][0][2]
        assert "TRACE Warning" in script

    def test_darwin_osascript_contains_message(self):
        from engine.notifier import _send_notification
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            _send_notification("title", "Projekt: myproject\nbody text")
        script = mock_popen.call_args[0][0][2]
        assert "myproject" in script

    def test_darwin_never_raises_on_osascript_error(self):
        from engine.notifier import _send_notification
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen", side_effect=OSError("no osascript")):
            mock_plat.system.return_value = "Darwin"
            _send_notification("title", "message")  # must not raise

    # ── Windows ────────────────────────────────────────────────────────────

    def test_calls_win10toast_on_windows_when_available(self):
        from engine.notifier import _send_notification
        mock_w10 = MagicMock()
        mock_toaster = MagicMock()
        mock_w10.ToastNotifier.return_value = mock_toaster

        with patch("engine.notifier.platform") as mock_plat, \
             patch.dict(sys.modules, {"win10toast": mock_w10}):
            mock_plat.system.return_value = "Windows"
            _send_notification("TRACE Warning", "message body")

        mock_w10.ToastNotifier.assert_called_once()
        mock_toaster.show_toast.assert_called_once()
        args, kwargs = mock_toaster.show_toast.call_args
        assert args[0] == "TRACE Warning"

    def test_win10toast_reset_title(self):
        from engine.notifier import _send_notification
        mock_w10 = MagicMock()
        mock_toaster = MagicMock()
        mock_w10.ToastNotifier.return_value = mock_toaster

        with patch("engine.notifier.platform") as mock_plat, \
             patch.dict(sys.modules, {"win10toast": mock_w10}):
            mock_plat.system.return_value = "Windows"
            _send_notification("TRACE Critical", "message body")

        args, _ = mock_toaster.show_toast.call_args
        assert args[0] == "TRACE Critical"

    def test_silent_when_win10toast_not_installed(self):
        """ImportError on win10toast must be swallowed silently."""
        from engine.notifier import _send_notification
        with patch("engine.notifier.platform") as mock_plat, \
             patch.dict(sys.modules, {"win10toast": None}):
            mock_plat.system.return_value = "Windows"
            _send_notification("title", "message")  # must not raise

    # ── Linux ──────────────────────────────────────────────────────────────

    def test_calls_notify_send_on_linux(self):
        from engine.notifier import _send_notification
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Linux"
            _send_notification("TRACE Warning", "Projekt: proj\nbody")
        assert mock_popen.call_count == 1
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "notify-send"

    def test_linux_notify_send_passes_title_and_message(self):
        from engine.notifier import _send_notification
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Linux"
            _send_notification("TRACE Warning", "Projekt: myproject\nbody")
        cmd = mock_popen.call_args[0][0]
        assert cmd[1] == "TRACE Warning"
        assert "myproject" in cmd[2]

    def test_linux_never_raises_on_notify_send_error(self):
        from engine.notifier import _send_notification
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen", side_effect=OSError("no notify-send")):
            mock_plat.system.return_value = "Linux"
            _send_notification("title", "message")  # must not raise

    # ── notify() integration ───────────────────────────────────────────────

    def test_notify_builds_body_with_project(self):
        """notify() composes the body containing project name before dispatch."""
        from engine.notifier import notify
        captured: list[tuple] = []
        with patch("engine.notifier._send_notification",
                   side_effect=lambda t, m: captured.append((t, m))), \
             patch("engine.notifier._play_sound"):
            notify("warn", 90_000, "my-project", _ENABLED_CONFIG)
        assert captured
        _, body = captured[0]
        assert "my-project" in body

    def test_notify_warn_title(self):
        from engine.notifier import notify
        captured: list[tuple] = []
        with patch("engine.notifier._send_notification",
                   side_effect=lambda t, m: captured.append((t, m))), \
             patch("engine.notifier._play_sound"):
            notify("warn", 90_000, "proj", _ENABLED_CONFIG)
        title, _ = captured[0]
        assert title == "TRACE Warning"

    def test_notify_reset_title(self):
        from engine.notifier import notify
        captured: list[tuple] = []
        with patch("engine.notifier._send_notification",
                   side_effect=lambda t, m: captured.append((t, m))), \
             patch("engine.notifier._play_sound"):
            notify("reset", 160_000, "proj", _ENABLED_CONFIG)
        title, _ = captured[0]
        assert title == "TRACE Critical"

    def test_notify_body_contains_token_count(self):
        from engine.notifier import notify
        captured: list[tuple] = []
        with patch("engine.notifier._send_notification",
                   side_effect=lambda t, m: captured.append((t, m))), \
             patch("engine.notifier._play_sound"):
            notify("reset", 160_000, "proj", _ENABLED_CONFIG)
        _, body = captured[0]
        assert "160,000" in body


# ---------------------------------------------------------------------------
# engine/notifier._play_sound() – platform-specific sound
# ---------------------------------------------------------------------------

class TestPlaySound:
    def test_calls_afplay_on_darwin(self):
        from engine.notifier import _play_sound
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            _play_sound("warn", _ENABLED_CONFIG["notifications"])
        assert mock_popen.call_count == 1
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "afplay"

    def test_warn_uses_tink_on_darwin(self):
        from engine.notifier import _play_sound
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            _play_sound("warn", _ENABLED_CONFIG["notifications"])
        cmd = mock_popen.call_args[0][0]
        assert "Tink" in cmd[1]

    def test_reset_uses_funk_on_darwin(self):
        from engine.notifier import _play_sound
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            _play_sound("reset", _ENABLED_CONFIG["notifications"])
        cmd = mock_popen.call_args[0][0]
        assert "Funk" in cmd[1]

    def test_calls_winsound_on_windows(self):
        from engine.notifier import _play_sound
        mock_winsound = MagicMock()
        mock_winsound.SND_ALIAS = 0x00010000
        mock_winsound.SND_ASYNC = 0x00000001
        with patch("engine.notifier.platform") as mock_plat, \
             patch.dict(sys.modules, {"winsound": mock_winsound}):
            mock_plat.system.return_value = "Windows"
            _play_sound("warn", _ENABLED_CONFIG["notifications"])
        mock_winsound.PlaySound.assert_called_once()
        args = mock_winsound.PlaySound.call_args[0]
        assert args[0] == "SystemAsterisk"

    def test_winsound_reset_uses_system_exclamation(self):
        from engine.notifier import _play_sound
        mock_winsound = MagicMock()
        mock_winsound.SND_ALIAS = 0x00010000
        mock_winsound.SND_ASYNC = 0x00000001
        with patch("engine.notifier.platform") as mock_plat, \
             patch.dict(sys.modules, {"winsound": mock_winsound}):
            mock_plat.system.return_value = "Windows"
            _play_sound("reset", _ENABLED_CONFIG["notifications"])
        args = mock_winsound.PlaySound.call_args[0]
        assert args[0] == "SystemExclamation"

    def test_calls_paplay_on_linux(self):
        from engine.notifier import _play_sound
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Linux"
            _play_sound("warn", _ENABLED_CONFIG["notifications"])
        assert mock_popen.call_count == 1
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "paplay"

    def test_linux_reset_uses_bell_sound(self):
        from engine.notifier import _play_sound
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Linux"
            _play_sound("reset", _ENABLED_CONFIG["notifications"])
        cmd = mock_popen.call_args[0][0]
        assert "bell" in cmd[1]

    def test_no_sound_when_disabled_via_notify(self):
        """sound=False: notify() skips _play_sound entirely."""
        from engine.notifier import notify
        with patch("engine.notifier._send_notification"), \
             patch("engine.notifier._play_sound") as mock_sound:
            notify("warn", 90_000, "proj", _NO_SOUND_CONFIG)
        mock_sound.assert_not_called()

    def test_never_raises_on_afplay_error(self):
        from engine.notifier import _play_sound
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen", side_effect=OSError("no such file")):
            mock_plat.system.return_value = "Darwin"
            _play_sound("warn", _ENABLED_CONFIG["notifications"])


# ---------------------------------------------------------------------------
# LiveTracker notification integration tests
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_store(tmp_path):
    config = {
        "trace": {"db_path": "test.db", "version": "0.1.0"},
        "projects": [],
        "budgets": {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
        "session_health": _SESSION_HEALTH_CFG,
        "models": _MODEL_PRICES,
        "notifications": {"enabled": True, "sound": False},
    }
    cfg_path = tmp_path / "trace_config.yaml"
    cfg_path.write_text(yaml.dump(config))
    store = TraceStore(str(cfg_path))
    store.init_db()
    return store


@pytest.fixture
def patched_env(tmp_path, tmp_store, monkeypatch):
    """Redirect all live_tracker paths and inject a tmp store."""
    live_dir    = tmp_path / "live"
    live_dir.mkdir()
    last_health = tmp_path / "last_health.json"
    legacy      = tmp_path / "live_session.json"
    monkeypatch.setattr(lt_module, "_LIVE_DIR",          live_dir)
    monkeypatch.setattr(lt_module, "_LIVE_PATH",         legacy)
    monkeypatch.setattr(lt_module, "_LAST_HEALTH_PATH",  last_health)
    monkeypatch.setattr(lt_module, "_get_default_store", lambda: tmp_store)
    return live_dir


def _write_transcript(tmp_path: Path, turns: list[dict]) -> Path:
    p = tmp_path / "transcript.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for turn in turns:
            f.write(json.dumps(turn) + "\n")
    return p


def _assistant_turn(request_id: str, input_tokens: int = 0, output_tokens: int = 0,
                    cache_creation: int = 0) -> dict:
    return {
        "type": "assistant",
        "requestId": request_id,
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": 0,
                "output_tokens": output_tokens,
            },
        },
    }


class TestLiveTrackerNotifications:
    def test_ok_to_warn_fires_notify(self, tmp_path, patched_env):
        """Crossing warn threshold triggers notify('warn', ...)."""
        transcript = _write_transcript(tmp_path, [
            _assistant_turn("r1", input_tokens=1_200),  # > warn_tokens=1000
        ])
        notify_calls: list[tuple] = []
        with patch("engine.notifier.notify", side_effect=lambda *a, **kw: notify_calls.append(a)):
            LiveTracker(None).update(str(transcript), str(tmp_path))
        assert len(notify_calls) == 1
        assert notify_calls[0][0] == "warn"

    def test_ok_to_reset_fires_notify_reset(self, tmp_path, patched_env):
        """Jumping straight from ok to critical fires notify('reset', ...)."""
        transcript = _write_transcript(tmp_path, [
            _assistant_turn("r1", input_tokens=2_100),  # > critical_tokens=2000
        ])
        notify_calls: list[tuple] = []
        with patch("engine.notifier.notify", side_effect=lambda *a, **kw: notify_calls.append(a)):
            LiveTracker(None).update(str(transcript), str(tmp_path))
        assert len(notify_calls) == 1
        assert notify_calls[0][0] == "reset"

    def test_warn_to_reset_fires_notify(self, tmp_path, patched_env):
        """Escalating from warn→reset triggers another notification."""
        transcript = _write_transcript(tmp_path, [
            _assistant_turn("r1", input_tokens=1_200),
        ])
        with patch("engine.notifier.notify"):
            LiveTracker(None).update(str(transcript), str(tmp_path))

        transcript.write_text(
            json.dumps(_assistant_turn("r1", input_tokens=1_200)) + "\n" +
            json.dumps(_assistant_turn("r2", input_tokens=1_200)) + "\n"
        )
        notify_calls: list[tuple] = []
        with patch("engine.notifier.notify", side_effect=lambda *a, **kw: notify_calls.append(a)):
            LiveTracker(None).update(str(transcript), str(tmp_path))
        assert len(notify_calls) == 1
        assert notify_calls[0][0] == "reset"

    def test_reset_to_ok_does_not_fire(self, tmp_path, patched_env):
        """New session starting with green health: no notification."""
        transcript = _write_transcript(tmp_path, [
            _assistant_turn("r1", input_tokens=100),  # well under warn threshold
        ])
        notify_calls: list[tuple] = []
        with patch("engine.notifier.notify", side_effect=lambda *a, **kw: notify_calls.append(a)):
            LiveTracker(None).update(str(transcript), str(tmp_path))
        assert notify_calls == []

    def test_no_duplicate_notification_same_status(self, tmp_path, patched_env):
        """Staying in warn zone on repeated calls: notify fires only once."""
        transcript = _write_transcript(tmp_path, [
            _assistant_turn("r1", input_tokens=1_200),
        ])
        notify_calls: list[tuple] = []
        with patch("engine.notifier.notify", side_effect=lambda *a, **kw: notify_calls.append(a)):
            LiveTracker(None).update(str(transcript), str(tmp_path))
        transcript.write_text(
            json.dumps(_assistant_turn("r1", input_tokens=1_200)) + "\n" +
            json.dumps(_assistant_turn("r2", input_tokens=200)) + "\n"
        )
        with patch("engine.notifier.notify", side_effect=lambda *a, **kw: notify_calls.append(a)):
            LiveTracker(None).update(str(transcript), str(tmp_path))
        assert len(notify_calls) == 1


# ---------------------------------------------------------------------------
# Dashboard – POST /api/settings and /api/status notification fields
# ---------------------------------------------------------------------------

@pytest.fixture
def settings_home(tmp_path, monkeypatch):
    """Redirect TRACE_HOME, skip project sync."""
    import dashboard.server as srv

    config = {
        "trace": {"db_path": "test.db", "version": "0.1.0"},
        "projects": [],
        "budgets": {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
        "session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000},
        "models": _MODEL_PRICES,
        "notifications": {"enabled": True, "sound": True},
    }
    central = tmp_path / "trace_config.yaml"
    central.write_text(yaml.dump(config))

    store = TraceStore(str(central))
    store.init_db()

    monkeypatch.setattr(srv, "TRACE_HOME", tmp_path)
    monkeypatch.setattr(srv, "_store", lambda: store)

    def _no_sync(path: Path, cfg: dict) -> None:
        text = yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False)
        path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(srv, "_save_and_sync_config", _no_sync)

    return tmp_path


def test_post_settings_updates_config(settings_home):
    from fastapi.testclient import TestClient
    from dashboard.server import app

    client = TestClient(app)
    res = client.post("/api/settings", json={"notifications_enabled": False, "notifications_sound": False})
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    saved = yaml.safe_load((settings_home / "trace_config.yaml").read_text())
    assert saved["notifications"]["enabled"] is False
    assert saved["notifications"]["sound"] is False


def test_post_settings_partial_update(settings_home):
    """Only provided fields are changed; others remain."""
    from fastapi.testclient import TestClient
    from dashboard.server import app

    client = TestClient(app)
    client.post("/api/settings", json={"notifications_enabled": False})

    saved = yaml.safe_load((settings_home / "trace_config.yaml").read_text())
    assert saved["notifications"]["enabled"] is False
    assert saved["notifications"]["sound"] is True  # unchanged


def test_api_status_returns_notification_fields(settings_home):
    from fastapi.testclient import TestClient
    from dashboard.server import app

    client = TestClient(app)
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert "notifications_enabled" in data
    assert "notifications_sound"   in data
    assert data["notifications_enabled"] is True
    assert data["notifications_sound"]   is True


def test_api_status_notifications_default_true_when_block_missing(tmp_path, monkeypatch):
    """If notifications block is absent, /api/status defaults both fields to True."""
    import dashboard.server as srv
    from fastapi.testclient import TestClient
    from dashboard.server import app

    config = {
        "trace": {"db_path": "test.db", "version": "0.1.0"},
        "projects": [],
        "budgets": {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
        "session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000},
        "models": _MODEL_PRICES,
    }
    central = tmp_path / "trace_config.yaml"
    central.write_text(yaml.dump(config))
    store = TraceStore(str(central))
    store.init_db()
    monkeypatch.setattr(srv, "_store", lambda: store)

    client = TestClient(app)
    data = client.get("/api/status").json()
    assert data["notifications_enabled"] is True
    assert data["notifications_sound"]   is True
