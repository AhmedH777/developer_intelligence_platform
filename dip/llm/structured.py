"""Validated structured output from local models.

Local models frequently wrap JSON in prose or code fences and occasionally emit
invalid JSON. This helper extracts the JSON object, validates it against a
Pydantic schema, and — on failure — makes exactly one repair request before
failing safe (the plan's §12.3 policy).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from dip.llm.client import LLMClient, Message

T = TypeVar("T", bound=BaseModel)


@dataclass
class StructuredResult(Generic[T]):
    value: T | None
    error: str | None
    raw_text: str
    repaired: bool
    model: str = "local-model"

    @property
    def ok(self) -> bool:
        return self.value is not None


def extract_json_object(text: str) -> str | None:
    """Return the first balanced top-level ``{...}`` object found in ``text``.

    Tolerates surrounding prose and ```json fences, and ignores braces that
    appear inside string literals.
    """

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _try_parse(text: str, schema: type[T]) -> tuple[T | None, str | None]:
    candidate = extract_json_object(text)
    if candidate is None:
        return None, "No JSON object found in the response."
    try:
        return schema.model_validate_json(candidate), None
    except ValidationError as exc:
        return None, f"Schema validation failed: {exc.errors(include_url=False)}"
    except ValueError as exc:
        return None, f"Invalid JSON: {exc}"


def generate_structured(
    llm: LLMClient,
    messages: list[Message],
    schema: type[T],
    *,
    max_repairs: int = 1,
) -> StructuredResult[T]:
    response = llm.generate(messages)
    text = response.text
    model = response.model
    value, error = _try_parse(text, schema)
    if value is not None:
        return StructuredResult(value=value, error=None, raw_text=text, repaired=False, model=model)

    if max_repairs > 0:
        repair = Message(
            role="user",
            content=(
                "Your previous reply could not be parsed into the required JSON "
                f"schema. Error: {error}\n"
                "Reply again with ONLY a single valid JSON object that matches the "
                "schema. No prose, no markdown code fences."
            ),
        )
        retry = messages + [Message(role="assistant", content=text), repair]
        response = llm.generate(retry)
        text = response.text
        model = response.model
        value, error = _try_parse(text, schema)
        if value is not None:
            return StructuredResult(
                value=value, error=None, raw_text=text, repaired=True, model=model
            )

    return StructuredResult(
        value=None, error=error, raw_text=text, repaired=max_repairs > 0, model=model
    )
