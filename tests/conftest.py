from __future__ import annotations

from pathlib import Path

import pytest

from dip.container import Container
from dip.core.config import Settings
from dip.llm.client import LLMResponse, Message

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


class FakeLLM:
    """Deterministic stand-in for a local model. Records the messages it sees."""

    def __init__(self, reply: str = "This function adds a value to a total.") -> None:
        self.reply = reply
        self.last_messages: list[Message] | None = None

    def generate(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.last_messages = messages
        return LLMResponse(text=self.reply, model="fake-model", raw={"fake": True})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.storage_dir = tmp_path / ".dip"
    return s


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def container(settings: Settings, fake_llm: FakeLLM) -> Container:
    return Container.create(settings=settings, llm=fake_llm)


@pytest.fixture
def sample_repo() -> Path:
    return FIXTURE_REPO
