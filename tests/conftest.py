import pytest
import yaml

from engine.store import TraceStore

_MODEL_PRICES = {
    "claude-sonnet-4-5": {"input_per_1k": 0.003, "output_per_1k": 0.015},
    "gpt-4o": {"input_per_1k": 0.005, "output_per_1k": 0.015},
}


@pytest.fixture
def tmp_store(tmp_path):
    """Fresh TraceStore backed by a real SQLite file in a temporary directory."""
    config = {
        "trace": {"db_path": "test.db", "version": "0.1.0"},
        "projects": [],
        "budgets": {"default_monthly_usd": 20.0, "alert_threshold_pct": 80},
        "models": _MODEL_PRICES,
    }
    config_path = tmp_path / "trace_config.yaml"
    config_path.write_text(yaml.dump(config))

    store = TraceStore(str(config_path))
    store.init_db()
    return store
