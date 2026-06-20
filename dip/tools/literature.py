"""Literature providers for the Research Scout.

``LiteratureProvider`` is the seam; ``NullLiteratureProvider`` is the offline
default and ``OpenAlexLiteratureProvider`` queries the public OpenAlex API (no
key required). The OpenAlex client is reconciled with the user's Scholar_search
implementation — field selection, polite-pool headers, retry/backoff on
429/5xx, the three search modes, inverted-index abstract decoding, and
cursor-paginated citations / batched reference fetches — adapted to the
platform's stdlib-only HTTP and secure TLS. Network/parse errors degrade to an
empty result so the Scout never breaks offline.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol, runtime_checkable

from dip.core.models import LiteratureItem

__all__ = [
    "LiteratureItem",
    "LiteratureProvider",
    "NullLiteratureProvider",
    "OpenAlexLiteratureProvider",
    "SEARCH_MODES",
]

API = "https://api.openalex.org"
WORK_SELECT = (
    "id,title,publication_year,authorships,cited_by_count,referenced_works,"
    "abstract_inverted_index,open_access,doi,primary_location"
)
SEARCH_MODES = ("title", "description", "author")


@runtime_checkable
class LiteratureProvider(Protocol):
    available: bool

    def search(self, query: str, limit: int = 5) -> list[LiteratureItem]: ...

    def gather(self, query: str, limit: int = 5, expand: bool = True) -> list[LiteratureItem]: ...


class NullLiteratureProvider:
    """Offline default: no external lookups. Keeps the Scout fully offline."""

    available: bool = False

    def search(self, query: str, limit: int = 5) -> list[LiteratureItem]:
        return []

    def gather(self, query: str, limit: int = 5, expand: bool = True) -> list[LiteratureItem]:
        return []


# ----- pure helpers (no network; unit-testable) -----------------------------
def short_id(openalex_url: str) -> str:
    return openalex_url.rstrip("/").split("/")[-1]


def decode_inverted_index(idx: dict[str, list[int]] | None) -> str:
    """Reconstruct an abstract from OpenAlex's {word: [positions]} format."""

    if not idx:
        return ""
    flat = [(pos, word) for word, positions in idx.items() for pos in positions]
    flat.sort()
    return " ".join(w for _, w in flat)


def _sanitize_filter_value(q: str) -> str:
    """OpenAlex separates filters with commas, so strip them from a value."""

    return (q or "").replace(",", " ").strip()


def _search_params(query: str, mode: str, n: int) -> dict[str, Any]:
    """Build /works query params for a search mode (pure; testable)."""

    params: dict[str, Any] = {"per-page": n, "select": WORK_SELECT}
    if mode == "author":
        params["filter"] = f"raw_author_name.search:{_sanitize_filter_value(query)}"
        params["sort"] = "cited_by_count:desc"
    elif mode == "description":
        params["filter"] = f"title_and_abstract.search:{_sanitize_filter_value(query)}"
    else:  # "title" (default): broad relevance search over title/abstract/fulltext
        params["search"] = query
    return params


def _to_item(work: dict[str, Any], snippet_words: int = 40) -> LiteratureItem:
    authors = [
        (a.get("author") or {}).get("display_name", "")
        for a in (work.get("authorships") or [])
    ]
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    venue = source.get("display_name", "") if isinstance(source, dict) else ""
    oa_url = (work.get("open_access") or {}).get("oa_url")
    url = oa_url or work.get("doi") or work.get("id") or ""

    abstract = decode_inverted_index(work.get("abstract_inverted_index"))
    words = abstract.split()
    snippet = " ".join(words[:snippet_words]) + ("…" if len(words) > snippet_words else "")

    return LiteratureItem(
        title=work.get("title") or work.get("display_name") or "(untitled)",
        year=work.get("publication_year"),
        authors=[a for a in authors if a],
        venue=venue or "",
        url=url,
        cited_by_count=work.get("cited_by_count", 0) or 0,
        abstract_snippet=snippet,
    )


class OpenAlexLiteratureProvider:
    """Query OpenAlex. No API key needed; ``mailto`` opts into the polite pool.

    Mirrors Scholar_search's client (retry/backoff, field select, search modes,
    citations/references) but uses stdlib ``urllib`` with TLS verification on.
    Errors are swallowed by the public methods so the Scout still works offline.
    """

    available: bool = True

    def __init__(self, mailto: str = "", timeout: int = 30, retries: int = 4) -> None:
        self._mailto = mailto
        self._timeout = timeout
        self._retries = retries

    # ----- public API -------------------------------------------------------
    def search(self, query: str, limit: int = 5, mode: str = "title") -> list[LiteratureItem]:
        if not query.strip():
            return []
        n = max(1, min(limit, 25))
        try:
            works = self._search_works(query, mode, n)
        except Exception:
            return []
        return [_to_item(w) for w in works[:limit]]

    def gather(
        self, query: str, limit: int = 5, expand: bool = True, seeds: int = 2
    ) -> list[LiteratureItem]:
        """Search for seed papers, expand via their references + citations, then
        dedupe and rank: seeds first (by relevance), expansions by citation count.

        This produces a richer, more relevant neighborhood than a flat search,
        which surfaces foundations and follow-up work for better grounding.
        """

        if not query.strip():
            return []
        try:
            seed_works = self._search_works(query, "title", max(seeds, limit))
        except Exception:
            return []

        works: dict[str, dict[str, Any]] = {}
        order: list[str] = []

        def add(work: dict[str, Any]) -> None:
            wid = short_id(work.get("id", ""))
            if wid not in works:
                works[wid] = work
                order.append(wid)

        for w in seed_works:
            add(w)
        seed_ids = {short_id(w.get("id", "")) for w in seed_works[:seeds]}

        if expand:
            for w in seed_works[:seeds]:
                refs = (w.get("referenced_works") or [])[:50]
                try:
                    for rw in self._works_by_ids(refs).values():
                        add(rw)
                except Exception:
                    pass
                try:
                    for cw in self._citation_works(w.get("id", ""), 10):
                        add(cw)
                except Exception:
                    pass

        seeds_in_order = [works[i] for i in order if i in seed_ids]
        others = [works[i] for i in order if i not in seed_ids]
        others.sort(key=lambda w: -(w.get("cited_by_count") or 0))
        return [_to_item(w) for w in (seeds_in_order + others)[:limit]]

    def fetch_works_by_ids(self, ids: list[str]) -> dict[str, LiteratureItem]:
        """Batch-fetch (50 at a time) -> {short_id: item}. Used for references."""

        try:
            raw = self._works_by_ids(ids)
        except Exception:
            return {}
        return {k: _to_item(v) for k, v in raw.items()}

    def fetch_citations(self, work_id: str, limit: int) -> list[LiteratureItem]:
        """Cursor-paginate works that cite ``work_id``, most-cited first."""

        try:
            return [_to_item(w) for w in self._citation_works(work_id, limit)]
        except Exception:
            return []

    # ----- raw fetchers (return OpenAlex work dicts) ------------------------
    def _search_works(self, query: str, mode: str, n: int) -> list[dict[str, Any]]:
        data = self._get("works", _search_params(query, mode, n))
        return data.get("results") or []

    def _works_by_ids(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        if not ids:
            return out
        sids = [short_id(w) for w in ids]
        for i in range(0, len(sids), 50):
            chunk = sids[i : i + 50]
            data = self._get(
                "works",
                {"filter": "openalex:" + "|".join(chunk), "per-page": len(chunk), "select": WORK_SELECT},
            )
            for w in data.get("results", []):
                out[short_id(w["id"])] = w
        return out

    def _citation_works(self, work_id: str, limit: int) -> list[dict[str, Any]]:
        short = short_id(work_id)
        out: list[dict[str, Any]] = []
        cursor: str | None = "*"
        while cursor and len(out) < limit:
            page = min(200, limit - len(out))
            data = self._get(
                "works",
                {
                    "filter": f"cites:{short}",
                    "per-page": page,
                    "sort": "cited_by_count:desc",
                    "cursor": cursor,
                    "select": WORK_SELECT,
                },
            )
            results = data.get("results", [])
            if not results:
                break
            out.extend(results)
            cursor = (data.get("meta") or {}).get("next_cursor")
        return out[:limit]

    # ----- HTTP -------------------------------------------------------------
    def _user_agent(self) -> str:
        return f"dev-intel-platform ({self._mailto})" if self._mailto else "dev-intel-platform"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = dict(params or {})
        if self._mailto:
            merged.setdefault("mailto", self._mailto)
        url = f"{API}/{path}?{urllib.parse.urlencode(merged)}"
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": self._user_agent()})
                with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (429, 500, 502, 503, 504):
                    time.sleep(3 * (2 ** attempt) + random.uniform(0, 1))
                    continue
                raise
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last = exc
                time.sleep(2 + attempt * 3)
        raise RuntimeError(f"OpenAlex request failed after {self._retries} retries: {last}")
