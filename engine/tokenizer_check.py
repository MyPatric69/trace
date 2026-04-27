"""Standalone daily tokenizer ratio check.

Reads the current and baseline model, calls Anthropic's count_tokens API
twice with a fixed reference text, and writes a ratio JSON to
~/.trace/tokenizer_ratio.json.

Run once daily via macOS LaunchAgent (see hooks/setup_tokenizer_check.sh).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

TRACE_HOME  = Path.home() / ".trace"
RATIO_FILE  = TRACE_HOME / "tokenizer_ratio.json"
CONFIG_FILE = TRACE_HOME / "trace_config.yaml"

# Fixed reference text – never change; ratio comparability depends on it.
REFERENCE_TEXT = """\
## Token Efficiency in Large Language Models

Modern language models use subword tokenization (BPE or similar).
The number of tokens a model assigns to identical text can differ
between model families – sometimes by 5–15%.

```python
def calculate_cost(input_tokens: int, output_tokens: int,
                   price_per_1k_input: float,
                   price_per_1k_output: float) -> float:
    return (input_tokens  / 1000 * price_per_1k_input
            + output_tokens / 1000 * price_per_1k_output)
```

Consider a session with 50,000 input tokens and 5,000 output tokens.
At $0.003/1k input and $0.015/1k output the cost is:

    cost = (50000/1000 * 0.003) + (5000/1000 * 0.015)
         = 0.15 + 0.075
         = $0.225 per session

Multiply by 20 sessions/day → $4.50/day → roughly $135/month.
Small per-session differences compound quickly at scale.

The tokenizer ratio (current_tokens / baseline_tokens) tells you whether
your active model uses more or fewer tokens than the baseline for the same
input – giving a truer picture of effective cost than the rate card alone.

Key insight: two models can have the same published price per 1k tokens yet
one may produce 10–15% more tokens for identical input, making it measurably
more expensive in practice. This script quantifies that difference daily so
cost comparisons in the dashboard reflect real-world token counts, not just
nominal pricing.
"""


def _load_config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_current_model(config: dict) -> str:
    """Determine active model: live session > recent DB session > config default."""
    live_dir = TRACE_HOME / "live"
    if live_dir.is_dir():
        candidates = sorted(
            live_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for f in candidates:
            try:
                m = json.loads(f.read_text()).get("model", "")
                if m:
                    return m
            except Exception:
                pass
    db = TRACE_HOME / "trace.db"
    if db.exists():
        try:
            con = sqlite3.connect(str(db))
            row = con.execute(
                "SELECT model FROM sessions ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            con.close()
            if row and row[0]:
                return row[0]
        except Exception:
            pass
    models = config.get("models", {})
    for m in models:
        if m.startswith("claude-"):
            return m
    return config.get("comparison", {}).get("baseline_model", "claude-sonnet-4-6")


def _count_tokens(model: str, text: str, api_key: str) -> int:
    payload = json.dumps({
        "model":    model,
        "messages": [{"role": "user", "content": text}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages/count_tokens",
        data=payload,
        headers={
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return int(json.loads(resp.read())["input_tokens"])


def run() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ANTHROPIC_API_KEY not set – skipping tokenizer check", file=sys.stderr)
        sys.exit(1)

    config         = _load_config()
    baseline_model = config.get("comparison", {}).get("baseline_model", "claude-sonnet-4-6")
    current_model  = _get_current_model(config)
    ref_hash       = hashlib.sha256(REFERENCE_TEXT.encode()).hexdigest()

    if current_model == baseline_model:
        result = {
            "current_model":       current_model,
            "baseline_model":      baseline_model,
            "current_tokens":      0,
            "baseline_tokens":     0,
            "ratio":               1.0,
            "checked_at":          datetime.now(timezone.utc).isoformat(),
            "reference_text_hash": ref_hash,
        }
        TRACE_HOME.mkdir(parents=True, exist_ok=True)
        RATIO_FILE.write_text(json.dumps(result, indent=2))
        print(f"Same model ({current_model}) – ratio is 1.0")
        return

    current_tokens  = _count_tokens(current_model,  REFERENCE_TEXT, api_key)
    baseline_tokens = _count_tokens(baseline_model, REFERENCE_TEXT, api_key)
    ratio = round(current_tokens / baseline_tokens, 4) if baseline_tokens else 1.0

    result = {
        "current_model":       current_model,
        "baseline_model":      baseline_model,
        "current_tokens":      current_tokens,
        "baseline_tokens":     baseline_tokens,
        "ratio":               ratio,
        "checked_at":          datetime.now(timezone.utc).isoformat(),
        "reference_text_hash": ref_hash,
    }
    TRACE_HOME.mkdir(parents=True, exist_ok=True)
    RATIO_FILE.write_text(json.dumps(result, indent=2))
    print(f"Tokenizer ratio {current_model}/{baseline_model} = {ratio}")


if __name__ == "__main__":
    run()
