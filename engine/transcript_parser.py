"""Shared transcript parsing used by session_logger and live_tracker.

Extracted so both consumers share identical token-counting logic without
duplication.  Callers must configure the root logger (or a handler on the
``engine.transcript_parser`` logger) before relying on error output.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

_log = logging.getLogger(__name__)

_SANITY_LIMIT = 200_000


def parse_transcript(transcript_path: str) -> dict:
    """Parse a Claude Code transcript.jsonl and return token usage summary.

    Real transcript format (Claude Code >= 1.x):
    - Each line has a ``type`` field: "user", "assistant", "attachment", etc.
    - Only ``type: "assistant"`` lines carry token usage.
    - Each assistant line has a ``message`` dict with ``model`` and ``usage``.
    - ``usage`` contains: ``input_tokens``, ``cache_creation_input_tokens``,
      ``cache_read_input_tokens``, ``output_tokens``.
    - Claude Code writes **multiple entries per API request** (same ``requestId``,
      different ``uuid``).  We deduplicate by ``requestId`` to avoid double-counting.

    Input token total = input_tokens + cache_creation_input_tokens.
    ``cache_read_input_tokens`` is intentionally excluded: it re-counts the same cached
    context on every API request, producing session totals many times the actual context
    window size (e.g. 87 requests x 20K cached context = 1.7M for a ~200K session).

    Returns:
        dict with keys: input_tokens, cache_creation_tokens, cache_read_tokens,
        output_tokens, model, turns.
        All values are 0 / "unknown" if the file is missing or unparseable.
    """
    path = Path(transcript_path)
    if not path.exists():
        return {
            "input_tokens": 0, "cache_creation_tokens": 0, "cache_read_tokens": 0,
            "output_tokens": 0, "peak_context_tokens": 0, "model": "unknown", "turns": 0,
        }

    input_tokens          = 0
    cache_creation_tokens = 0
    cache_read_tokens     = 0
    output_tokens         = 0
    peak_context_tokens   = 0
    model_counts: Counter = Counter()
    turns = 0
    seen_request_ids: set = set()

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Only assistant turns carry usage data
                if obj.get("type") != "assistant":
                    continue

                # Deduplicate: Claude Code emits multiple entries per requestId
                request_id = obj.get("requestId")
                if request_id:
                    if request_id in seen_request_ids:
                        continue
                    seen_request_ids.add(request_id)

                turns += 1

                msg = obj.get("message") or {}
                if not isinstance(msg, dict):
                    continue

                # Model
                model_field = msg.get("model")
                if isinstance(model_field, str) and model_field:
                    model_counts[model_field] += 1

                # Usage – read ONLY the four top-level token fields.
                # usage["iterations"] contains per-step breakdowns of the
                # same totals; summing from it would double-count every token.
                usage = msg.get("usage") or {}
                if isinstance(usage, dict):
                    turn_input             = int(usage.get("input_tokens")                  or 0)
                    input_tokens          += turn_input
                    cache_creation_tokens += int(usage.get("cache_creation_input_tokens")   or 0)
                    cache_read_tokens     += int(usage.get("cache_read_input_tokens")       or 0)
                    output_tokens         += int(usage.get("output_tokens")                 or 0)
                    if turn_input > peak_context_tokens:
                        peak_context_tokens = turn_input

    except Exception as exc:
        _log.error("parse_transcript failed for %s: %s", transcript_path, exc)
        return {
            "input_tokens": 0, "cache_creation_tokens": 0, "cache_read_tokens": 0,
            "output_tokens": 0, "peak_context_tokens": 0, "model": "unknown", "turns": 0,
        }

    model = model_counts.most_common(1)[0][0] if model_counts else "unknown"

    # Sanity check: warn when combined input context exceeds a single context window.
    # cache_read excluded here – it re-counts cached context on every request and
    # would trigger the warning on every turn of a cached session.
    effective_input = input_tokens + cache_creation_tokens
    if effective_input > _SANITY_LIMIT:
        _log.warning(
            "parse_transcript: effective_input=%d (input=%d + cache_creation=%d) "
            "exceeds %d for %s (long session – value recorded as-is)",
            effective_input, input_tokens, cache_creation_tokens,
            _SANITY_LIMIT, transcript_path,
        )

    return {
        "input_tokens":          input_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens":     cache_read_tokens,
        "output_tokens":         output_tokens,
        "peak_context_tokens":   peak_context_tokens,
        "model":                 model,
        "turns":                 turns,
    }
