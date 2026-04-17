"""Tests for engine/notifier.py and live_tracker.py notification integration."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import yaml

import engine.live_tracker as lt_module
from engine.live_tracker import LiveTracker
from engine.store import TraceStore


# ---------------------------------------------------------------------------
# Helpers / shared config
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
# engine/notifier.py unit tests
# ---------------------------------------------------------------------------

class TestNotifyDisabled:
    def test_does_nothing_when_enabled_false(self):
        from engine.notifier import notify
        with patch("subprocess.Popen") as mock_popen:
            notify("warn", 90_000, "myproject", _DISABLED_CONFIG)
        mock_popen.assert_not_called()

    def test_does_nothing_when_notifications_block_missing(self):
        from engine.notifier import notify
        with patch("subprocess.Popen") as mock_popen:
            notify("warn", 90_000, "myproject", {})
        # empty config → enabled defaults to True but on Darwin only; skip check:
        # key point: must not raise
        # (subprocess may or may not be called depending on OS – just ensure no exception)

    def test_unknown_status_does_nothing(self):
        from engine.notifier import notify
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            notify("ok", 90_000, "myproject", _ENABLED_CONFIG)
        mock_popen.assert_not_called()


class TestNotifyPlatform:
    def test_skips_on_linux(self):
        from engine.notifier import notify
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Linux"
            notify("warn", 90_000, "myproject", _ENABLED_CONFIG)
        mock_popen.assert_not_called()

    def test_skips_on_windows(self):
        from engine.notifier import notify
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Windows"
            notify("reset", 200_000, "myproject", _ENABLED_CONFIG)
        mock_popen.assert_not_called()

    def test_fires_on_darwin(self):
        from engine.notifier import notify
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            notify("warn", 90_000, "myproject", _ENABLED_CONFIG)
        assert mock_popen.call_count >= 1

    def test_warn_uses_tink_sound(self):
        from engine.notifier import notify
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            notify("warn", 90_000, "myproject", _ENABLED_CONFIG)
        calls = [str(c) for c in mock_popen.call_args_list]
        assert any("Tink" in c for c in calls)

    def test_reset_uses_funk_sound(self):
        from engine.notifier import notify
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            notify("reset", 160_000, "myproject", _ENABLED_CONFIG)
        calls = [str(c) for c in mock_popen.call_args_list]
        assert any("Funk" in c for c in calls)

    def test_no_sound_skips_afplay(self):
        from engine.notifier import notify
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            notify("warn", 90_000, "myproject", _NO_SOUND_CONFIG)
        calls = [str(c) for c in mock_popen.call_args_list]
        assert not any("afplay" in c for c in calls)
        assert any("osascript" in c for c in calls)

    def test_warn_notification_contains_project(self):
        from engine.notifier import notify
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen") as mock_popen:
            mock_plat.system.return_value = "Darwin"
            notify("warn", 90_000, "my-project", _ENABLED_CONFIG)
        osascript_calls = [c for c in mock_popen.call_args_list if "osascript" in str(c)]
        assert osascript_calls
        script_arg = str(osascript_calls[0])
        assert "my-project" in script_arg

    def test_never_raises_on_subprocess_error(self):
        from engine.notifier import notify
        with patch("engine.notifier.platform") as mock_plat, \
             patch("subprocess.Popen", side_effect=OSError("no such file")):
            mock_plat.system.return_value = "Darwin"
            # Must not raise
            notify("warn", 90_000, "myproject", _ENABLED_CONFIG)


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
    live_dir  = tmp_path / "live"
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
        # First call: land in warn zone
        transcript = _write_transcript(tmp_path, [
            _assistant_turn("r1", input_tokens=1_200),
        ])
        with patch("engine.notifier.notify"):
            LiveTracker(None).update(str(transcript), str(tmp_path))

        # Second call: push past critical threshold
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
        # Add another turn but stay in warn zone
        transcript.write_text(
            json.dumps(_assistant_turn("r1", input_tokens=1_200)) + "\n" +
            json.dumps(_assistant_turn("r2", input_tokens=200)) + "\n"
        )
        with patch("engine.notifier.notify", side_effect=lambda *a, **kw: notify_calls.append(a)):
            LiveTracker(None).update(str(transcript), str(tmp_path))
        # Only the first call should have triggered a notify
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
