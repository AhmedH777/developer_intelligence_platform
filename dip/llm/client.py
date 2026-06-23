"""Local LLM client abstraction.

Defines a small ``LLMClient`` Protocol so workflows depend on an interface, not a
vendor SDK. The concrete implementation targets any OpenAI-compatible local
endpoint (Ollama, LM Studio, llama.cpp server). Tests use a fake client, so no
network or model is required to exercise the workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from dip.core.config import LLMSettings


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    text: str
    model: str
    raw: dict[str, Any]


@runtime_checkable
class LLMClient(Protocol):
    def generate(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...


class OpenAICompatibleClient:
    """Talks to a local OpenAI-compatible chat-completions endpoint."""

    def __init__(self, settings: LLMSettings) -> None:
        self._settings = settings
        self._client: Any | None = None  # lazy import so tests need no openai

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # actionable message instead of "No module named openai"
                raise RuntimeError(
                    "The 'openai' package is required to call the local model. "
                    "Install it in the environment running the app: "
                    "`python -m pip install openai` (or `pip install -e \".[dev]\"`)."
                ) from exc

            self._client = OpenAI(
                base_url=self._settings.base_url,
                api_key=self._settings.api_key or "not-needed",
            )
        return self._client

    def generate(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        client = self._ensure_client()
        completion = client.chat.completions.create(
            model=self._settings.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=(
                self._settings.temperature if temperature is None else temperature
            ),
            max_tokens=self._settings.max_tokens if max_tokens is None else max_tokens,
        )
        text = completion.choices[0].message.content or ""
        raw = completion.model_dump() if hasattr(completion, "model_dump") else {}
        return LLMResponse(text=text, model=self._settings.model, raw=raw)
