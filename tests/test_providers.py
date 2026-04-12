"""Tests for engine/providers/ – provider adapter system."""
from __future__ import annotations

import os
import pytest
import yaml

from engine.providers import get_provider
from engine.providers.base import AbstractProvider
from engine.providers.manual import ManualProvider
from engine.providers.anthropic import AnthropicProvider
from engine.providers.openai import OpenAIProvider
from engine.providers.vertexai import VertexAIProvider
from engine.store import TraceStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MODEL_PRICES = {
    "claude-sonnet-4-5": {
        "input_per_1k": 0.003, "output_per_1k": 0.015,
        "cache_creation_per_1k": 0.00375, "cache_read_per_1k": 0.0003,
    },
}


@pytest.fixture
def tmp_store(tmp_path):
    config = {
        "trace": {"db_path": "test.db", "version": "0.2.0"},
        "projects": [],
        "budgets": {"default_monthly_usd": 25.0, "alert_threshold_pct": 80},
        "session": {"warn_at_tokens": 60_000, "recommend_reset_at": 100_000},
        "models": _MODEL_PRICES,
        "api_integration": {
            "provider": "manual",
            "sync_usage": False,
            "budget_source": "manual",
            "monthly_budget_usd": 25.0,
        },
    }
    cfg = tmp_path / "trace_config.yaml"
    cfg.write_text(yaml.dump(config))
    store = TraceStore(str(cfg))
    store.init_db()
    return store


@pytest.fixture
def tmp_config(tmp_store):
    return tmp_store.config


# ---------------------------------------------------------------------------
# ManualProvider – is_available
# ---------------------------------------------------------------------------

def test_manual_provider_is_always_available():
    assert ManualProvider().is_available() is True


def test_manual_provider_get_name():
    assert ManualProvider().get_name() == "manual"


# ---------------------------------------------------------------------------
# ManualProvider – get_usage structure
# ---------------------------------------------------------------------------

def test_manual_get_usage_returns_required_keys():
    p = ManualProvider()
    usage = p.get_usage("month")
    for key in ("provider", "period", "input_tokens", "output_tokens",
                "cache_tokens", "total_cost_usd", "budget_usd", "currency", "source"):
        assert key in usage, f"Missing key: {key}"


def test_manual_get_usage_source_is_local():
    assert ManualProvider().get_usage()["source"] == "local"


def test_manual_get_usage_provider_field():
    assert ManualProvider().get_usage()["provider"] == "manual"


def test_manual_get_usage_currency():
    assert ManualProvider().get_usage()["currency"] == "USD"


def test_manual_get_usage_integer_token_fields():
    usage = ManualProvider().get_usage()
    assert isinstance(usage["input_tokens"],  int)
    assert isinstance(usage["output_tokens"], int)
    assert isinstance(usage["cache_tokens"],  int)


def test_manual_get_usage_period_propagated():
    for period in ("today", "week", "month", "all"):
        assert ManualProvider().get_usage(period)["period"] == period


def test_manual_get_usage_sums_sessions(tmp_store, monkeypatch):
    tmp_store.add_project("alpha", "/projects/alpha")
    tmp_store.add_session("alpha", "claude-sonnet-4-5", 1000, 500,
                          cache_creation_tokens=200)

    def fake_default():
        return tmp_store

    monkeypatch.setattr(TraceStore, "default", staticmethod(fake_default))
    usage = ManualProvider().get_usage("all")
    assert usage["input_tokens"]  == 1000
    assert usage["output_tokens"] == 500
    assert usage["cache_tokens"]  == 200  # cache_creation + cache_read (0)


# ---------------------------------------------------------------------------
# ManualProvider – get_models
# ---------------------------------------------------------------------------

def test_manual_get_models_returns_list():
    assert isinstance(ManualProvider().get_models(), list)


def test_manual_get_models_structure(tmp_store, monkeypatch):
    monkeypatch.setattr(TraceStore, "default", staticmethod(lambda: tmp_store))
    models = ManualProvider().get_models()
    assert len(models) >= 1
    for m in models:
        for key in ("id", "input_per_1k", "output_per_1k",
                    "cache_creation_per_1k", "cache_read_per_1k"):
            assert key in m, f"Model missing key: {key}"


# ---------------------------------------------------------------------------
# AnthropicProvider – credentials not present in test environment
# ---------------------------------------------------------------------------

def test_anthropic_not_available_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Prevent Keychain subprocess from succeeding in tests
    import subprocess
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: type("R", (), {"returncode": 1, "stdout": ""})())
    assert AnthropicProvider().is_available() is False


def test_anthropic_get_name():
    assert AnthropicProvider().get_name() == "anthropic"


def test_anthropic_get_usage_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import subprocess
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: type("R", (), {"returncode": 1, "stdout": ""})())
    usage = AnthropicProvider().get_usage("month")
    assert usage["provider"] == "anthropic"
    assert usage["source"]   == "local"


def test_anthropic_get_models_returns_list():
    models = AnthropicProvider().get_models()
    assert isinstance(models, list)
    assert len(models) > 0


def test_anthropic_models_have_required_keys():
    for m in AnthropicProvider().get_models():
        for key in ("id", "input_per_1k", "output_per_1k",
                    "cache_creation_per_1k", "cache_read_per_1k"):
            assert key in m


# ---------------------------------------------------------------------------
# OpenAIProvider – credentials not present in test environment
# ---------------------------------------------------------------------------

def test_openai_not_available_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert OpenAIProvider().is_available() is False


def test_openai_get_name():
    assert OpenAIProvider().get_name() == "openai"


def test_openai_get_usage_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    usage = OpenAIProvider().get_usage("month")
    assert usage["provider"] == "openai"
    assert usage["source"]   == "local"


def test_openai_get_models_returns_empty_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert OpenAIProvider().get_models() == []


# ---------------------------------------------------------------------------
# VertexAIProvider – credentials not present in test environment
# ---------------------------------------------------------------------------

def test_vertexai_not_available_without_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    # Ensure ADC file doesn't exist
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: None)
    # Override home so ADC path doesn't resolve
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))
    assert VertexAIProvider().is_available() is False


def test_vertexai_get_name():
    assert VertexAIProvider().get_name() == "vertexai"


def test_vertexai_get_models_returns_list():
    models = VertexAIProvider().get_models()
    assert isinstance(models, list)
    assert len(models) > 0


def test_vertexai_models_have_required_keys():
    for m in VertexAIProvider().get_models():
        for key in ("id", "input_per_1k", "output_per_1k",
                    "cache_creation_per_1k", "cache_read_per_1k"):
            assert key in m


# ---------------------------------------------------------------------------
# get_provider() – dispatch and fallback
# ---------------------------------------------------------------------------

def test_get_provider_returns_manual_by_default(tmp_config):
    p = get_provider(tmp_config)
    assert isinstance(p, ManualProvider)


def test_get_provider_manual_explicit(tmp_config):
    tmp_config.setdefault("api_integration", {})["provider"] = "manual"
    p = get_provider(tmp_config)
    assert isinstance(p, ManualProvider)


def test_get_provider_unknown_name_returns_manual(tmp_config):
    tmp_config.setdefault("api_integration", {})["provider"] = "doesnotexist"
    p = get_provider(tmp_config)
    assert isinstance(p, ManualProvider)


def test_get_provider_unavailable_returns_manual(tmp_config, monkeypatch):
    tmp_config.setdefault("api_integration", {})["provider"] = "anthropic"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import subprocess
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: type("R", (), {"returncode": 1, "stdout": ""})())
    p = get_provider(tmp_config)
    assert isinstance(p, ManualProvider)


def test_get_provider_returns_abstract_provider_instance(tmp_config):
    p = get_provider(tmp_config)
    assert isinstance(p, AbstractProvider)


def test_get_provider_returned_provider_is_available(tmp_config):
    p = get_provider(tmp_config)
    assert p.is_available() is True
