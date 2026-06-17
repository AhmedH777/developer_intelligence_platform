from __future__ import annotations

from pydantic import BaseModel

from dip.llm.client import LLMResponse, Message
from dip.llm.structured import extract_json_object, generate_structured


class Demo(BaseModel):
    name: str
    count: int


class ScriptedLLM:
    """Returns a queued list of replies, one per call."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = replies
        self.calls = 0

    def generate(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
        reply = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return LLMResponse(text=reply, model="scripted", raw={})


def test_extract_json_object_strips_fences_and_prose() -> None:
    text = 'Sure! Here you go:\n```json\n{"name": "x", "count": 2}\n```\nHope that helps.'
    extracted = extract_json_object(text)
    assert extracted == '{"name": "x", "count": 2}'


def test_extract_json_ignores_braces_in_strings() -> None:
    text = '{"name": "a } b", "count": 1}'
    assert extract_json_object(text) == text


def test_clean_first_pass_succeeds() -> None:
    llm = ScriptedLLM(['{"name": "ok", "count": 3}'])
    result = generate_structured(llm, [Message("user", "go")], Demo)
    assert result.ok
    assert result.value == Demo(name="ok", count=3)
    assert result.repaired is False
    assert llm.calls == 1


def test_repair_on_second_attempt() -> None:
    llm = ScriptedLLM(["not json at all", '{"name": "fixed", "count": 5}'])
    result = generate_structured(llm, [Message("user", "go")], Demo)
    assert result.ok
    assert result.value == Demo(name="fixed", count=5)
    assert result.repaired is True
    assert llm.calls == 2


def test_fail_safe_after_repair_exhausted() -> None:
    llm = ScriptedLLM(["nope", "still nope"])
    result = generate_structured(llm, [Message("user", "go")], Demo)
    assert not result.ok
    assert result.value is None
    assert result.error is not None
    assert llm.calls == 2
