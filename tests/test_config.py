"""Unit tests for engine/config.py – TraceConfig."""
import pytest
import yaml

from engine.config import TraceConfig, _USER_KEYS, _USER_DEFAULTS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sys_cfg(tmp_path):
    path = tmp_path / "system.yaml"
    path.write_text(yaml.dump({
        "models": {
            "claude-sonnet-4-6": {"input_per_1k": 0.003, "output_per_1k": 0.015},
            "claude-haiku-4-5":  {"input_per_1k": 0.0008, "output_per_1k": 0.004},
        },
        "trace": {"version": "0.3.0"},
    }))
    return path


@pytest.fixture
def user_path(tmp_path):
    return tmp_path / "user_config.yaml"


@pytest.fixture
def legacy_cfg(tmp_path):
    path = tmp_path / "trace_config.yaml"
    path.write_text(yaml.dump({
        "session_health": {"warn_tokens": 90_000, "critical_tokens": 180_000},
        "notifications":  {"enabled": False, "sound": False},
        "mcp_servers":    [{"name": "github"}],
        "budgets":        {"default_monthly_usd": 50.0},
        "comparison":     {"baseline_model": "claude-haiku-4-5"},
        "models":         {"claude-sonnet-4-6": {"input_per_1k": 999.0}},
    }))
    return path


# ---------------------------------------------------------------------------
# Merging: system config provides models, user config provides preferences
# ---------------------------------------------------------------------------

def test_merged_contains_system_models(sys_cfg, user_path):
    user_path.write_text(yaml.dump(
        {"session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000}}
    ))
    tc = TraceConfig(sys_cfg, user_path)
    assert "claude-sonnet-4-6" in tc.merged["models"]
    assert tc.merged["models"]["claude-sonnet-4-6"]["input_per_1k"] == 0.003


def test_merged_uses_user_session_health(sys_cfg, user_path):
    user_path.write_text(yaml.dump(
        {"session_health": {"warn_tokens": 60_000, "critical_tokens": 120_000}}
    ))
    tc = TraceConfig(sys_cfg, user_path)
    assert tc.merged["session_health"]["warn_tokens"] == 60_000
    assert tc.merged["session_health"]["critical_tokens"] == 120_000


def test_system_models_not_overridden_by_user(sys_cfg, user_path):
    user_path.write_text(yaml.dump({
        "models":         {"claude-sonnet-4-6": {"input_per_1k": 999.0}},
        "session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000},
    }))
    tc = TraceConfig(sys_cfg, user_path)
    assert tc.merged["models"]["claude-sonnet-4-6"]["input_per_1k"] == 0.003


def test_user_comparison_overrides_system_default(sys_cfg, user_path):
    user_path.write_text(yaml.dump(
        {"comparison": {"baseline_model": "claude-haiku-4-5"}}
    ))
    tc = TraceConfig(sys_cfg, user_path)
    assert tc.merged["comparison"]["baseline_model"] == "claude-haiku-4-5"


def test_missing_user_keys_fall_back_to_defaults(sys_cfg, user_path):
    user_path.write_text(yaml.dump({}))
    tc = TraceConfig(sys_cfg, user_path)
    assert tc.merged["session_health"] == _USER_DEFAULTS["session_health"]
    assert tc.merged["notifications"]  == _USER_DEFAULTS["notifications"]


# ---------------------------------------------------------------------------
# Migration: user_config.yaml created from legacy trace_config.yaml
# ---------------------------------------------------------------------------

def test_migration_creates_user_config_from_legacy(sys_cfg, user_path, legacy_cfg):
    tc = TraceConfig(sys_cfg, user_path, _legacy_path=legacy_cfg)
    assert user_path.exists()
    saved = yaml.safe_load(user_path.read_text())
    assert saved["session_health"]["warn_tokens"] == 90_000
    assert saved["notifications"]["enabled"] is False
    assert saved["mcp_servers"] == [{"name": "github"}]


def test_migration_excludes_system_keys(sys_cfg, user_path, legacy_cfg):
    TraceConfig(sys_cfg, user_path, _legacy_path=legacy_cfg)
    saved = yaml.safe_load(user_path.read_text())
    assert "models" not in saved
    assert "trace" not in saved


def test_migration_skipped_when_user_config_exists(sys_cfg, user_path, legacy_cfg):
    user_path.write_text(yaml.dump(
        {"session_health": {"warn_tokens": 10_000, "critical_tokens": 20_000}}
    ))
    TraceConfig(sys_cfg, user_path, _legacy_path=legacy_cfg)
    saved = yaml.safe_load(user_path.read_text())
    assert saved["session_health"]["warn_tokens"] == 10_000


def test_migration_fills_missing_keys_with_defaults(tmp_path, sys_cfg, user_path):
    partial_legacy = tmp_path / "partial.yaml"
    partial_legacy.write_text(yaml.dump(
        {"session_health": {"warn_tokens": 50_000, "critical_tokens": 100_000}}
    ))
    TraceConfig(sys_cfg, user_path, _legacy_path=partial_legacy)
    saved = yaml.safe_load(user_path.read_text())
    assert "notifications" in saved
    assert saved["notifications"]["enabled"] == _USER_DEFAULTS["notifications"]["enabled"]


# ---------------------------------------------------------------------------
# get_model_price
# ---------------------------------------------------------------------------

def test_get_model_price_exact_match(sys_cfg, user_path):
    user_path.write_text(yaml.dump({}))
    tc = TraceConfig(sys_cfg, user_path)
    prices = tc.get_model_price("claude-sonnet-4-6")
    assert prices is not None
    assert prices["input_per_1k"] == 0.003


def test_get_model_price_prefix_match(sys_cfg, user_path):
    user_path.write_text(yaml.dump({}))
    tc = TraceConfig(sys_cfg, user_path)
    prices = tc.get_model_price("claude-sonnet-4-6-20251022")
    assert prices is not None
    assert prices["input_per_1k"] == 0.003


def test_get_model_price_unknown_returns_none(sys_cfg, user_path):
    user_path.write_text(yaml.dump({}))
    tc = TraceConfig(sys_cfg, user_path)
    assert tc.get_model_price("unknown-model-xyz") is None


# ---------------------------------------------------------------------------
# save_user_setting / save_user_config
# ---------------------------------------------------------------------------

def test_save_user_setting_writes_to_user_file_only(sys_cfg, user_path):
    user_path.write_text(yaml.dump(
        {"session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000}}
    ))
    tc = TraceConfig(sys_cfg, user_path)
    tc.save_user_setting("session_health", {"warn_tokens": 50_000, "critical_tokens": 100_000})
    saved = yaml.safe_load(user_path.read_text())
    assert saved["session_health"]["warn_tokens"] == 50_000
    assert "models" not in saved


def test_save_user_config_rebuilds_merged(sys_cfg, user_path):
    user_path.write_text(yaml.dump(
        {"session_health": {"warn_tokens": 80_000, "critical_tokens": 150_000}}
    ))
    tc = TraceConfig(sys_cfg, user_path)
    tc.user_config["session_health"]["warn_tokens"] = 40_000
    tc.save_user_config()
    assert tc.merged["session_health"]["warn_tokens"] == 40_000
    assert tc.merged["models"]["claude-sonnet-4-6"]["input_per_1k"] == 0.003
