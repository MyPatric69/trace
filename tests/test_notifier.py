"""Tests for engine/notifier.py and live_tracker.py notification integration."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
# Helper: plyer mock
# ---------------------------------------------------------------------------

def _plyer_mock():
    """Return a MagicMock that replaces plyer.notification."""
    return MagicMock()


# ---------------------------------------------------------------------------
# engine/notifier.py – disabled / unknown status
# ---------------------------------------------------------------------------

class TestNotifyDisabled:
    def test_does_nothing_when_enabled_false(self):
        from engine.notifier import notify
        mock_plyer = _plyer_mock()
        with patch.dict(sys.modules, {"plyer": MagicMock(notification=mock_plyer)}), \
             patch("subprocess.Popen") as mock_popen:
            notify("warn", 90_000, "myproject", _DISABLED_CONFIG)
        mock_plyer.notify.assert_not_called()
        mock_popen.assert_not_called()

    def test_does_nothing_when_notifications_block_missing(self):
        """Empty config: enabled defaults True – must not raise regardless."""
        from engine.notifier import notify
        mock_plyer = _plyer_mock()
        with patch.dict(sys.modules, {"plyer": MagicMock(notification=mock_plyer)}), \
             patch("subprocess.Popen"):
            notify("warn", 90_000, "myproject", {})
        # No assertion – just verifying no exception

    def test_unknown_status_does_nothing(self):
        from engine.notifier import notify
        mock_plyer = _plyer_mock()
        with patch.dict(sys.modules, {"plyer": MagicMock(notification=mock_plyer)}), \
             patch("subprocess.Popen") as mock_popen:
            notify("ok", 90_000, "myproject", _ENABLED_CONFIG)
        mock_plyer.notify.assert_not_called()
        mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# engine/notifier.py – notify() uses plyer on all platforms
# ---------------------------------------------------------------------------

class TestNotifyPlyer:
    def _call_notify(self, status: str, system: str, config: dict = _ENABLED_CONFIG):
        from engine.notifier import notify
        mock_plyer = _plyer_mock()
        with patch.dict(sys.modules, {"plyer": MagicMock(notification=mock_plyer)}), \
             patch("engine.notifier.platform") as mock_plat, \
             patch("engine.notifier._play_sound"):
            mock_plat.system.return_value = system
            notify(status, 90_000, "myproject", config)
        return mock_plyer

    def test_uses_plyer_on_darwin(self):
        mock_plyer = self._call_notify("warn", "Darwin")
        mock_plyer.notify.assert_called_once()

    def test_uses_plyer_on_linux(self):
        mock_plyer = self._call_notify("warn", "Linux")
        mock_plyer.notify.assert_called_once()

    def test_uses_plyer_on_windows(self):
        mock_plyer = self._call_notify("warn", "Windows")
        mock_plyer.notify.assert_called_once()

    def test_warn_message_contains_project(self):
        from engine.notifier import notify
        mock_plyer = _plyer_mock()
        with patch.dict(sys.modules, {"plyer": MagicMock(notification=mock_plyer)}), \
             patch("engine.notifier._play_sound"):
            notify("warn", 90_000, "my-project", _ENABLED_CONFIG)
        _, kwargs = mock_plyer.notify.call_args
        assert "my-project" in kwargs.get("message", "")

    def test_reset_message_contains_token_count(self):
        from engine.notifier import notify
        mock_plyer = _plyer_mock()
        with patch.dict(sys.modules, {"plyer": MagicMock(notification=mock_plyer)}), \
             patch("engine.notifier._play_sound"):
            notify("reset", 160_000, "proj", _ENABLED_CONFIG)
        _, kwargs = mock_plyer.notify.call_args
        assert "160,000" in kwargs.get("message", "")

    def test_warn_title_is_trace_warning(self):
        from engine.notifier import notify
        mock_plyer = _plyer_mock()
        with patch.dict(sys.modules, {"plyer": MagicMock(notification=mock_plyer)}), \
             patch("engine.notifier._play_sound"):
            notify("warn", 90_000, "proj", _ENABLED_CONFIG)
        _, kwargs = mock_plyer.notify.call_args
        assert kwargs.get("title") == "TRACE Warning"

    def test_reset_title_is_trace_kritisch(self):
        from engine.notifier import notify
        mock_plyer = _plyer_mock()
        with patch.dict(sys.modules, {"plyer": MagicMock(notification=mock_plyer)}), \
             patch("engine.notifier._play_sound"):
            notify("reset", 160_000, "proj", _ENABLED_CONFIG)
        _, kwargs = mock_plyer.notify.call_args
        assert kwargs.get("title") == "TRACE Kritisch"

    def test_never_raises_when_plyer_unavailable(self):
        from engine.notifier import notify
        with patch.dict(sys.modules, {"plyer": None}), \
             patch("engine.notifier._play_sound"):
            notify("warn", 90_000, "proj", _ENABLED_CONFIG)

    def test_sound_skipped_when_sound_false(self):
        from engine.notifier import notify
        mock_plyer = _plyer_mock()
        with patch.dict(sys.modules, {"plyer": MagicMock(notification=mock_plyer)}), \
             patch("engine.notifier._play_sound") as mock_sound:
            notify("warn", 90_000, "proj", _NO_SOUND_CONFIG)
        mock_plyer.notify.assert_called_once()
        mock_sound.assert_not_called()


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

    def test_no_afplay_when_sound_false_via_notify(self):
        """sound=False: notify() skips _play_sound entirely."""
        from engine.notifier import notify
        mock_plyer = _plyer_mock()
        with patch.dict(sys.modules, {"plyer": MagicMock(notification=mock_plyer)}), \
             patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            notify("warn", 90_000, "proj", _NO_SOUND_CONFIG)
        mock_popen.assert_not_called()

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
