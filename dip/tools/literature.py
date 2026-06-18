"""Literature providers for the Research Scout.

The Scout can ground proposals in real papers. ``LiteratureProvider`` is the
seam; ``NullLiteratureProvider`` is the offline default and ``OpenAlexLiterature
Provider`` queries the public OpenAlex API (no key required). Network failures
degrade gracefully to an empty result so the Scout never breaks offline.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Protocol, runtime_checkable

from dip.core.models import LiteratureItem

__all__ = [
    "LiteratureItem",
    "LiteratureProvider",
    "NullLiteratureProvider",
    "OpenAlexLiteratureProvider",
]


@runtime_checkable
class LiteratureProvider(Protocol):
    available: bool

    def search(self, query: str, limit: int = 5) -> list[LiteratureItem]: ...


class NullLiteratureProvider:
    """Offline default: no external lookups. Keeps the Scout fully offline."""

    available: bool = False

    def search(self, query: str, limit: int = 5) -> list[LiteratureItem]:
        return []


class OpenAlexLiteratureProvider:
    """Query the public OpenAlex works API. No API key needed.

    Passing a contact email opts into OpenAlex's faster "polite pool". All
    network/parse errors are swallowed and return ``[]`` so the Scout still works
    when offline or rate-limited.
    """

    BASE_URL = "https://api.openalex.org/works"
    available: bool = True

    def __init__(self, mailto: str = "", timeout: int = 10) -> None:
        self._mailto = mailto
        self._timeout = timeout

    def search(self, query: str, limit: int = 5) -> list[LiteratureItem]:
        if not query.strip():
            return []
        params = {
            "search": query,
            "per_page": str(max(1, min(limit, 25))),
            "sort": "relevance_score:desc",
        }
        if self._mailto:
            params["mailto"] = self._mailto
        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
        try:
            data = self._fetch(url)
        except Exception:
            return []
        results = data.get("results", []) if isinstance(data, dict) else []
        return [_to_item(w) for w in results[:limit]]

    def _fetch(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": "dev-intel-platform"})
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))


def _to_item(work: dict[str, Any]) -> LiteratureItem:
    authors = [
        a.get("author", {}).get("display_name", "")
        for a in (work.get("authorships") or [])
        if a.get("author")
    ]
    venue = ""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    if isinstance(source, dict):
        venue = source.get("display_name", "") or ""
    return LiteratureItem(
        title=work.get("display_name") or work.get("title") or "(untitled)",
        year=work.get("publication_year"),
        authors=[a for a in authors if a],
        venue=venue,
        url=work.get("doi") or work.get("id") or "",
        cited_by_count=work.get("cited_by_count", 0) or 0,
        abstract_snippet=_abstract_snippet(work.get("abstract_inverted_index")),
    )


def _abstract_snippet(inverted: dict[str, list[int]] | None, max_words: int = 40) -> str:
    """Reconstruct a short abstract from OpenAlex's inverted index."""

    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    words = [w for _, w in positions[:max_words]]
    text = " ".join(words)
    return text + ("…" if len(positions) > max_words else "")
