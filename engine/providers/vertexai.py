"""VertexAIProvider – wraps Google Cloud Vertex AI / Cloud Billing API.

Credentials: GOOGLE_APPLICATION_CREDENTIALS env var, or application
default credentials (gcloud auth application-default login).

Budget tracking is optional and depends on Cloud Billing quota configuration.
Falls back to ManualProvider on any error.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

_TRACE_ROOT = Path(__file__).parents[2]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.providers.base import AbstractProvider

_log = logging.getLogger(__name__)

_TIMEOUT = 5  # seconds

# Hardcoded Gemini pricing (no public pricing API).
_VERTEX_MODELS: list[dict] = [
    {
        "id":                    "gemini-1.5-pro",
        "input_per_1k":          0.00125,
        "output_per_1k":         0.005,
        "cache_creation_per_1k": 0.0003125,
        "cache_read_per_1k":     0.0003125,
    },
    {
        "id":                    "gemini-1.5-flash",
        "input_per_1k":          0.000075,
        "output_per_1k":         0.0003,
        "cache_creation_per_1k": 0.00001875,
        "cache_read_per_1k":     0.00001875,
    },
    {
        "id":                    "gemini-2.0-flash",
        "input_per_1k":          0.0001,
        "output_per_1k":         0.0004,
        "cache_creation_per_1k": 0.000025,
        "cache_read_per_1k":     0.000025,
    },
]


def _has_credentials() -> bool:
    """Return True if Google application credentials are present."""
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        cred_path = Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
        if cred_path.exists():
            return True

    # Check gcloud application-default credentials
    adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    if adc_path.exists():
        return True

    # Check if gcloud CLI is available with active account
    if shutil.which("gcloud"):
        try:
            result = subprocess.run(
                ["gcloud", "auth", "application-default", "print-access-token"],
                capture_output=True, text=True, timeout=3,
            )
            return result.returncode == 0
        except Exception:
            pass

    return False


def _get_access_token() -> str | None:
    """Obtain a Google OAuth2 access token via gcloud."""
    try:
        result = subprocess.run(
            ["gcloud", "auth", "application-default", "print-access-token"],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


class VertexAIProvider(AbstractProvider):
    """Reads usage from Cloud Billing API; falls back to local DB.

    Note: budget_usd is None when no Cloud Billing quota is configured.
    Token-level usage data availability depends on your GCP project setup.
    """

    def get_name(self) -> str:
        return "vertexai"

    def is_available(self) -> bool:
        return _has_credentials()

    def get_usage(self, period: str = "month") -> dict:
        """Attempt Cloud Billing API; fall back to ManualProvider on failure."""
        if not self.is_available():
            return self._fallback(period)

        try:
            token = _get_access_token()
            if not token:
                return self._fallback(period)

            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")
            if not project_id:
                # Try to detect from gcloud config
                result = subprocess.run(
                    ["gcloud", "config", "get-value", "project"],
                    capture_output=True, text=True, timeout=3,
                )
                if result.returncode == 0 and result.stdout.strip():
                    project_id = result.stdout.strip()

            if not project_id:
                return self._fallback(period)

            # Cloud Billing API – get budget information
            req = urllib.request.Request(
                f"https://billingbudgets.googleapis.com/v1/billingAccounts/-/budgets",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read())

            budget_usd: float | None = None
            budgets = data.get("budgets") or []
            if budgets:
                amount = budgets[0].get("amount", {})
                specified = amount.get("specifiedAmount", {})
                if "units" in specified:
                    budget_usd = float(specified["units"])

            return {
                "provider":       "vertexai",
                "period":         period,
                "input_tokens":   0,
                "output_tokens":  0,
                "cache_tokens":   0,
                "total_cost_usd": None,
                "budget_usd":     budget_usd,
                "currency":       "USD",
                "source":         "api",
            }
        except Exception as exc:
            _log.warning("VertexAIProvider.get_usage failed (%s) – using local data", exc)
            return self._fallback(period)

    def get_models(self) -> list[dict]:
        return list(_VERTEX_MODELS)

    def _fallback(self, period: str) -> dict:
        from engine.providers.manual import ManualProvider
        result = ManualProvider().get_usage(period)
        result["provider"] = "vertexai"
        result["source"]   = "local"
        return result
