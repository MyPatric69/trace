"""Context compressor – generates a token-optimized re-entry prompt from AI_CONTEXT.md.

No LLM calls. All extraction is pure local text processing.
estimate_tokens() is an approximation only (words × 1.3).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import yaml

_TRACE_ROOT = Path(__file__).parents[1]
if str(_TRACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRACE_ROOT))

from engine.store import TraceStore  # noqa: E402


class ContextCompressor:
    """Reads AI_CONTEXT.md and produces a compact re-entry prompt."""

    def __init__(self, project_path: str, config_path: str = "trace_config.yaml") -> None:
        self.project_path = Path(project_path).resolve()

        cfg = Path(config_path)
        if not cfg.is_absolute():
            cfg = self.project_path / cfg
        self.config_path = cfg

        with open(cfg) as f:
            self.config = yaml.safe_load(f)

        health_cfg = self.config.get("session_health", {})
        self.warn_at: int = health_cfg.get("warn_tokens", 80_000)
        self.reset_at: int = health_cfg.get("critical_tokens", 150_000)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate_tokens(self, text: str) -> int:
        """Approximate token count. Uses words × 1.3. Not exact."""
        return int(len(text.split()) * 1.3)

    def compress(self, max_tokens: int = 2000) -> str:
        """Extract a compact re-entry prompt from AI_CONTEXT.md.

        Returns a markdown string under max_tokens. Falls back to the
        first 2000 characters of the raw file if section parsing fails.
        """
        content = self._read_context()
        if not content:
            return "(No AI_CONTEXT.md found.)"

        try:
            return self._build_compact(content, max_tokens)
        except Exception:
            return content[:2000]

    def get_session_recommendation(self) -> dict:
        """Compare today's token usage against thresholds in trace_config.yaml.

        Returns a dict with recommendation: "continue" | "warn" | "reset".
        compressed_context is included only when recommendation != "continue".
        """
        total_tokens, total_cost = self._fetch_today_totals()

        if total_tokens < self.warn_at:
            return {
                "total_tokens_today": total_tokens,
                "total_cost_today": total_cost,
                "recommendation": "continue",
                "message": f"Session is within normal range ({total_tokens:,} tokens today).",
            }

        if total_tokens < self.reset_at:
            recommendation = "warn"
            message = (
                f"Approaching session threshold ({total_tokens:,} tokens today). "
                "Consider a session reset soon."
            )
        else:
            recommendation = "reset"
            message = (
                f"Session reset recommended ({total_tokens:,} tokens today). "
                "Use new_session() to compress context and start fresh."
            )

        return {
            "total_tokens_today": total_tokens,
            "total_cost_today": total_cost,
            "recommendation": recommendation,
            "message": message,
            "compressed_context": self.compress(),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _read_context(self) -> str:
        path = self.project_path / "AI_CONTEXT.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _parse_section(self, content: str, heading: str) -> str:
        """Return the body of the first ## section whose heading starts with *heading*."""
        lines = content.split("\n")
        target = f"## {heading}"
        start: int | None = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == target or stripped.startswith(target):
                start = i + 1
                break
        if start is None:
            return ""

        body: list[str] = []
        for i in range(start, len(lines)):
            if lines[i].startswith("## ") or lines[i].strip() == "---":
                break
            body.append(lines[i])
        return "\n".join(body).strip()

    def _parse_project_name(self) -> str | None:
        """Extract the short project name from the ## Project section."""
        content = self._read_context()
        section = self._parse_section(content, "Project")
        for line in section.split("\n"):
            if "**Name:**" in line:
                after = line.split("**Name:**")[-1].strip()
                for sep in (" \u2013 ", " \u2014 ", " - "):  # en-dash, em-dash, hyphen
                    if sep in after:
                        return after.split(sep)[0].strip()
                return after
        return None

    def _fetch_today_totals(self) -> tuple[int, float]:
        """Return (total_tokens, total_cost_usd) for this project's sessions today."""
        project_name = self._parse_project_name()
        today = date.today().isoformat()
        total_tokens = 0
        total_cost = 0.0
        try:
            store = TraceStore(str(self.config_path))
            sessions = store.get_sessions(project_name=project_name, since_date=today)
            for s in sessions:
                total_tokens += s.get("input_tokens", 0) + s.get("output_tokens", 0)
                total_cost += s.get("cost_usd", 0.0)
        except Exception:
            pass  # no db yet or project not registered – treat as zero
        return total_tokens, round(total_cost, 6)

    def _build_compact(self, content: str, max_tokens: int) -> str:
        parts: list[str] = []

        # --- Project name + status ---
        project_section = self._parse_section(content, "Project")
        name_line = ""
        status_line = ""
        for line in project_section.split("\n"):
            if "**Name:**" in line:
                name_line = line.strip()
            if "**Status:**" in line:
                status_line = line.strip()
        if name_line or status_line:
            parts.append("## Project")
            if name_line:
                parts.append(name_line)
            if status_line:
                parts.append(status_line)

        # --- Architecture snapshot (up to 10 lines) ---
        arch_section = self._parse_section(content, "Architecture")
        if arch_section:
            arch_lines = arch_section.split("\n")
            arch_snippet = "\n".join(arch_lines[:10]).strip()
            parts.append("\n## Architecture")
            parts.append(arch_snippet)

        # --- Last 3 completed items + next 3 steps ---
        next_section = self._parse_section(content, "Next steps")
        if next_section:
            completed = [
                ln.strip()
                for ln in next_section.split("\n")
                if ln.strip().startswith("- [x]")
            ]
            upcoming = [
                ln.strip()
                for ln in next_section.split("\n")
                if ln.strip().startswith("- [ ]")
            ]
            if completed or upcoming:
                parts.append("\n## Progress")
                if completed:
                    parts.append("**Recently completed:**")
                    parts.extend(completed[-3:])
                if upcoming:
                    parts.append("**Next steps:**")
                    parts.extend(upcoming[:3])

        # --- Key decisions (max 3) ---
        decisions_section = self._parse_section(content, "Key decisions")
        if decisions_section:
            decisions = [
                ln.strip()
                for ln in decisions_section.split("\n")
                if ln.strip().startswith("- **")
            ]
            if decisions:
                parts.append("\n## Key decisions")
                parts.extend(decisions[:3])

        # --- Last updated ---
        last_updated = self._parse_section(content, "Last updated")
        if last_updated:
            parts.append(f"\n**Last updated:** {last_updated.strip()}")

        result = "\n".join(parts).strip()

        # Trim to max_tokens if needed (approximation)
        if self.estimate_tokens(result) > max_tokens:
            char_limit = int(max_tokens / 1.3 * 5)
            result = result[:char_limit].rstrip() + "\n...(truncated)"

        return result
