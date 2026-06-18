"""Literature provider seam.

The Research Scout can ground proposals in real papers. This module defines the
interface and an offline default; the OpenAlex implementation (ported from
``Scholar_search``) drops in later by implementing ``LiteratureProvider`` — no
changes to the workflow are needed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class LiteratureItem(BaseModel):
    title: str
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    venue: str = ""
    url: str = ""
    abstract_snippet: str = ""

    @property
    def citation(self) -> str:
        who = self.authors[0] + " et al." if self.authors else "Unknown"
        yr = f" ({self.year})" if self.year else ""
        return f"{who}{yr}. {self.title}"


@runtime_checkable
class LiteratureProvider(Protocol):
    def search(self, query: str, limit: int = 5) -> list[LiteratureItem]: ...


class NullLiteratureProvider:
    """Offline default: no external lookups. Keeps the Scout fully offline."""

    available: bool = False

    def search(self, query: str, limit: int = 5) -> list[LiteratureItem]:
        return []
