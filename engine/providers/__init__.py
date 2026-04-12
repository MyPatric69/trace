"""Provider adapter package for TRACE.

Usage::

    from engine.providers import get_provider
    provider = get_provider()          # uses trace_config.yaml setting
    usage    = provider.get_usage()    # normalized usage dict
    models   = provider.get_models()   # list of model dicts

The provider is selected by ``api_integration.provider`` in trace_config.yaml.
If the configured provider is unavailable, ManualProvider is used as fallback.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[2]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.providers.base import AbstractProvider
from engine.providers.manual import ManualProvider

_log = logging.getLogger(__name__)
_warned: bool = False  # suppress duplicate fallback warnings across calls

__all__ = ["get_provider", "AbstractProvider", "ManualProvider"]


def get_provider(config: dict | None = None) -> AbstractProvider:
    """Return a ready provider instance based on trace_config.yaml.

    Resolution order:
    1. ``api_integration.provider`` key in *config* (or ~/.trace/trace_config.yaml)
    2. If the configured provider is unavailable → log warning + use ManualProvider
    3. Default → ManualProvider

    Args:
        config: Optional pre-loaded config dict (for testing). If None the
                standard TraceStore.default() config is used.

    Returns:
        An AbstractProvider instance that is guaranteed to be available.
    """
    if config is None:
        try:
            from engine.store import TraceStore
            store = TraceStore.default()
            config = store.config
        except Exception as exc:
            _log.warning("get_provider: could not load config (%s), using ManualProvider", exc)
            return ManualProvider()

    provider_name = (
        (config.get("api_integration") or {}).get("provider", "manual") or "manual"
    ).lower().strip()

    provider = _build_provider(provider_name)

    if provider is None:
        _log.warning("get_provider: unknown provider %r – using ManualProvider", provider_name)
        return ManualProvider()

    if not isinstance(provider, ManualProvider) and not provider.is_available():
        global _warned
        if not _warned:
            _log.warning(
                "get_provider: provider %r is not available (credentials missing) "
                "– falling back to ManualProvider",
                provider_name,
            )
            _warned = True
        return ManualProvider()

    return provider


def _build_provider(name: str) -> AbstractProvider | None:
    """Instantiate the named provider; return None for unknown names."""
    match name:
        case "manual":
            return ManualProvider()
        case "anthropic":
            from engine.providers.anthropic import AnthropicProvider
            return AnthropicProvider()
        case "openai":
            from engine.providers.openai import OpenAIProvider
            return OpenAIProvider()
        case "vertexai":
            from engine.providers.vertexai import VertexAIProvider
            return VertexAIProvider()
        case _:
            return None
