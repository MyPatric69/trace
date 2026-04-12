"""ManualProvider – local DB only, no external credentials required.

This is the default provider.  It aggregates token usage directly from
~/.trace/trace.db and reads model pricing from trace_config.yaml.
It is always available and always succeeds.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[2]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.providers.base import AbstractProvider
from engine.store import TraceStore


class ManualProvider(AbstractProvider):
    """Default fallback provider – reads only from the local TRACE database."""

    def is_available(self) -> bool:
        return True

    def get_name(self) -> str:
        return "manual"

    def get_usage(self, period: str = "month") -> dict:
        """Aggregate sessions from ~/.trace/trace.db for the given period."""
        from datetime import date, timedelta

        try:
            store = TraceStore.default()
            store.init_db()

            since_date: str | None = None
            today = date.today()
            match period:
                case "today":
                    since_date = today.isoformat()
                case "week":
                    since_date = (today - timedelta(days=7)).isoformat()
                case "month":
                    since_date = (today - timedelta(days=30)).isoformat()
                case _:
                    since_date = None  # "all"

            tokens  = store.get_token_summary(since_date=since_date)
            costs   = store.get_cost_summary(since_date=since_date)
            budgets = store.config.get("budgets", {})

            cache_tokens = (
                tokens["total_cache_creation_tokens"]
                + tokens["total_cache_read_tokens"]
            )
            return {
                "provider":       "manual",
                "period":         period,
                "input_tokens":   tokens["total_input_tokens"],
                "output_tokens":  tokens["total_output_tokens"],
                "cache_tokens":   cache_tokens,
                "total_cost_usd": costs["total_cost_usd"],
                "budget_usd":     budgets.get("default_monthly_usd"),
                "currency":       "USD",
                "source":         "local",
            }
        except Exception:
            return {
                "provider":       "manual",
                "period":         period,
                "input_tokens":   0,
                "output_tokens":  0,
                "cache_tokens":   0,
                "total_cost_usd": 0.0,
                "budget_usd":     None,
                "currency":       "USD",
                "source":         "local",
            }

    def get_models(self) -> list[dict]:
        """Return model pricing from trace_config.yaml."""
        try:
            store = TraceStore.default()
            models = []
            for model_id, prices in store.model_prices.items():
                models.append({
                    "id":                    model_id,
                    "input_per_1k":          prices.get("input_per_1k",          0.0),
                    "output_per_1k":         prices.get("output_per_1k",         0.0),
                    "cache_creation_per_1k": prices.get("cache_creation_per_1k", 0.0),
                    "cache_read_per_1k":     prices.get("cache_read_per_1k",     0.0),
                })
            return models
        except Exception:
            return []
