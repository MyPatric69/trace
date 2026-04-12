"""OpenAIProvider – wraps the OpenAI Usage API.

Credentials: OPENAI_API_KEY environment variable.
Falls back to ManualProvider on any error.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[2]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.providers.base import AbstractProvider

_log = logging.getLogger(__name__)

_TIMEOUT = 5  # seconds


class OpenAIProvider(AbstractProvider):
    """Reads usage from the OpenAI Usage API; falls back to local DB."""

    def get_name(self) -> str:
        return "openai"

    def is_available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def get_usage(self, period: str = "month") -> dict:
        """Call OpenAI Usage API; fall back to ManualProvider on failure."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return self._fallback(period)

        try:
            from datetime import date, timedelta
            today = date.today()
            match period:
                case "today":
                    start = today.isoformat()
                case "week":
                    start = (today - timedelta(days=7)).isoformat()
                case "month":
                    start = (today - timedelta(days=30)).isoformat()
                case _:
                    start = None

            params = f"?date={start}" if start else ""

            req = urllib.request.Request(
                f"https://api.openai.com/v1/usage{params}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read())

            # OpenAI usage API returns a list under "data"
            entries = data.get("data") or []
            input_tokens  = sum(int(e.get("n_context_tokens_total",  0)) for e in entries)
            output_tokens = sum(int(e.get("n_generated_tokens_total", 0)) for e in entries)

            return {
                "provider":       "openai",
                "period":         period,
                "input_tokens":   input_tokens,
                "output_tokens":  output_tokens,
                "cache_tokens":   0,
                "total_cost_usd": None,
                "budget_usd":     None,
                "currency":       "USD",
                "source":         "api",
            }
        except Exception as exc:
            _log.warning("OpenAIProvider.get_usage failed (%s) – using local data", exc)
            return self._fallback(period)

    def get_models(self) -> list[dict]:
        """Fetch available models from OpenAI API; return empty list on failure."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return []

        try:
            req = urllib.request.Request(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read())

            models = []
            for m in (data.get("data") or []):
                models.append({
                    "id":                    m.get("id", ""),
                    "input_per_1k":          0.0,
                    "output_per_1k":         0.0,
                    "cache_creation_per_1k": 0.0,
                    "cache_read_per_1k":     0.0,
                })
            return models
        except Exception as exc:
            _log.warning("OpenAIProvider.get_models failed: %s", exc)
            return []

    def _fallback(self, period: str) -> dict:
        from engine.providers.manual import ManualProvider
        result = ManualProvider().get_usage(period)
        result["provider"] = "openai"
        result["source"]   = "local"
        return result
