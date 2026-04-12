"""AnthropicProvider – wraps the Anthropic Usage API.

Credentials (checked in order):
  1. ANTHROPIC_API_KEY environment variable
  2. macOS Keychain via:
     security find-generic-password -a "$USER" -s "ANTHROPIC_API_KEY" -w

If the API call fails the provider falls back to ManualProvider.get_usage().
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
import json
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[2]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.providers.base import AbstractProvider

_log = logging.getLogger(__name__)

_TIMEOUT = 5  # seconds for all network calls

# Hardcoded current Anthropic pricing (no public models/pricing API exists).
_ANTHROPIC_MODELS: list[dict] = [
    {
        "id":                    "claude-sonnet-4-6",
        "input_per_1k":          0.003,
        "output_per_1k":         0.015,
        "cache_creation_per_1k": 0.00375,
        "cache_read_per_1k":     0.0003,
    },
    {
        "id":                    "claude-sonnet-4-5",
        "input_per_1k":          0.003,
        "output_per_1k":         0.015,
        "cache_creation_per_1k": 0.00375,
        "cache_read_per_1k":     0.0003,
    },
    {
        "id":                    "claude-opus-4-5",
        "input_per_1k":          0.015,
        "output_per_1k":         0.075,
        "cache_creation_per_1k": 0.01875,
        "cache_read_per_1k":     0.0015,
    },
    {
        "id":                    "claude-haiku-4-5",
        "input_per_1k":          0.0008,
        "output_per_1k":         0.004,
        "cache_creation_per_1k": 0.001,
        "cache_read_per_1k":     0.00008,
    },
]


def _get_api_key() -> str | None:
    """Return API key from env or macOS Keychain; None if not found."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key

    # macOS Keychain fallback
    try:
        result = subprocess.run(
            ["security", "find-generic-password",
             "-a", os.environ.get("USER", ""),
             "-s", "ANTHROPIC_API_KEY", "-w"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass

    return None


class AnthropicProvider(AbstractProvider):
    """Reads usage from the Anthropic Usage API; falls back to local DB."""

    def get_name(self) -> str:
        return "anthropic"

    def is_available(self) -> bool:
        return _get_api_key() is not None

    def get_usage(self, period: str = "month") -> dict:
        """Call Anthropic Usage API; fall back to ManualProvider on failure."""
        api_key = _get_api_key()
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

            params = ""
            if start:
                params = f"?start_date={start}"

            req = urllib.request.Request(
                f"https://api.anthropic.com/v1/usage{params}",
                headers={
                    "x-api-key":         api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read())

            # Normalize – API shape may vary; use .get() for safety
            return {
                "provider":       "anthropic",
                "period":         period,
                "input_tokens":   int(data.get("input_tokens", 0)),
                "output_tokens":  int(data.get("output_tokens", 0)),
                "cache_tokens":   int(data.get("cache_creation_input_tokens", 0))
                                  + int(data.get("cache_read_input_tokens", 0)),
                "total_cost_usd": data.get("total_cost"),
                "budget_usd":     None,
                "currency":       "USD",
                "source":         "api",
            }
        except Exception as exc:
            _log.warning("AnthropicProvider.get_usage failed (%s) – using local data", exc)
            return self._fallback(period)

    def _fallback(self, period: str) -> dict:
        from engine.providers.manual import ManualProvider
        result = ManualProvider().get_usage(period)
        result["provider"] = "anthropic"
        result["source"]   = "local"
        return result

    def get_models(self) -> list[dict]:
        return list(_ANTHROPIC_MODELS)
