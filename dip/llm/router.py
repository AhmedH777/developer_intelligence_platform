"""Per-role model routing.

Each workflow gets an ``LLMClient`` for its role, so a planner, coder, reviewer,
debugger, and explainer can each use a different local model and temperature
(the plan's §12.2). Unconfigured roles fall back to the base settings, so the
default behavior is identical to a single shared model.

Tests inject a fake client via ``override``; the router then returns that same
client for every role, keeping the existing single-model tests valid.
"""

from __future__ import annotations

from dip.core.config import LLMSettings
from dip.llm.client import LLMClient, OpenAICompatibleClient

# Canonical role names.
PLANNER = "planner"
CODER = "coder"
REVIEWER = "reviewer"
DEBUGGER = "debugger"
EXPLAINER = "explainer"
SUMMARIZER = "summarizer"
RESEARCHER = "researcher"

ALL_ROLES = (PLANNER, CODER, REVIEWER, DEBUGGER, EXPLAINER, SUMMARIZER, RESEARCHER)


class LLMRouter:
    def __init__(self, base: LLMSettings, override: LLMClient | None = None) -> None:
        self._base = base
        self._override = override
        self._cache: dict[str, LLMClient] = {}

    def for_role(self, role: str) -> LLMClient:
        if self._override is not None:
            return self._override
        if role not in self._cache:
            self._cache[role] = OpenAICompatibleClient(self._base.for_role(role))
        return self._cache[role]

    def resolved_model(self, role: str) -> tuple[str, float]:
        """Return (model, temperature) that ``role`` will use — for display."""

        settings = self._base.for_role(role)
        return settings.model, settings.temperature
