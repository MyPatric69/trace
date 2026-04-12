"""Abstract base class for all TRACE provider adapters.

Each adapter wraps one AI provider (Anthropic, OpenAI, Vertex AI, or the
local DB fallback) behind a common interface.  New providers can be added
by subclassing AbstractProvider and registering the name in __init__.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractProvider(ABC):
    """Common interface every provider adapter must implement."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if credentials/config needed by this provider exist."""

    @abstractmethod
    def get_usage(self, period: str = "month") -> dict:
        """Return aggregated usage for the requested period.

        ``period`` is one of: "today", "week", "month", "all".

        Returns a dict with these keys (None for unsupported fields):

        {
            "provider":       str,
            "period":         str,
            "input_tokens":   int,
            "output_tokens":  int,
            "cache_tokens":   int,
            "total_cost_usd": float | None,
            "budget_usd":     float | None,
            "currency":       str,
            "source":         "api" | "local",
        }
        """

    @abstractmethod
    def get_models(self) -> list[dict]:
        """Return available models with per-1k-token pricing.

        Each entry:
        {
            "id":                    str,
            "input_per_1k":          float,
            "output_per_1k":         float,
            "cache_creation_per_1k": float,
            "cache_read_per_1k":     float,
        }
        """

    def get_name(self) -> str:
        """Human-readable provider identifier (lower-cased class name)."""
        return self.__class__.__name__.lower().replace("provider", "")
