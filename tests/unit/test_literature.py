from __future__ import annotations

from dip.core.models import LiteratureItem
from dip.tools.literature import (
    WORK_SELECT,
    NullLiteratureProvider,
    OpenAlexLiteratureProvider,
    _sanitize_filter_value,
    _search_params,
    _to_item,
    decode_inverted_index,
    short_id,
)

SAMPLE_WORK = {
    "id": "https://openalex.org/W123",
    "title": "Residual RL for Control",
    "publication_year": 2024,
    "authorships": [
        {"author": {"display_name": "A. Doe"}},
        {"author": {"display_name": "B. Roe"}},
    ],
    "primary_location": {"source": {"display_name": "NeurIPS"}},
    "open_access": {"oa_url": "https://oa.example/paper.pdf"},
    "doi": "https://doi.org/10.1/x",
    "cited_by_count": 42,
    "abstract_inverted_index": {"We": [0], "study": [1], "residual": [2], "RL": [3]},
}


def test_to_item_parses_and_prefers_oa_url() -> None:
    item = _to_item(SAMPLE_WORK)
    assert item.title == "Residual RL for Control"
    assert item.year == 2024
    assert item.authors == ["A. Doe", "B. Roe"]
    assert item.venue == "NeurIPS"
    assert item.cited_by_count == 42
    assert item.url == "https://oa.example/paper.pdf"  # open-access link preferred
    assert item.abstract_snippet == "We study residual RL"


def test_to_item_falls_back_to_doi_without_oa() -> None:
    work = {**SAMPLE_WORK, "open_access": {}}
    assert _to_item(work).url == "https://doi.org/10.1/x"


def test_decode_inverted_index_orders_by_position() -> None:
    assert decode_inverted_index({"b": [1], "a": [0], "c": [2]}) == "a b c"
    assert decode_inverted_index(None) == ""


def test_to_item_truncates_long_abstract() -> None:
    work = {"title": "T", "abstract_inverted_index": {f"w{i}": [i] for i in range(50)}}
    snippet = _to_item(work, snippet_words=5).abstract_snippet
    assert snippet.endswith("…")
    assert len(snippet.rstrip("…").split()) == 5


def test_search_params_modes() -> None:
    title = _search_params("graph nets", "title", 3)
    assert title["search"] == "graph nets" and "filter" not in title
    assert title["select"] == WORK_SELECT and title["per-page"] == 3

    desc = _search_params("graph, nets", "description", 5)
    assert desc["filter"] == "title_and_abstract.search:graph  nets"  # comma stripped

    author = _search_params("Y. LeCun", "author", 2)
    assert author["filter"] == "raw_author_name.search:Y. LeCun"
    assert author["sort"] == "cited_by_count:desc"


def test_sanitize_and_short_id() -> None:
    assert _sanitize_filter_value("a, b, c") == "a  b  c"
    assert short_id("https://openalex.org/W42/") == "W42"


def test_null_provider_offline() -> None:
    p = NullLiteratureProvider()
    assert p.available is False
    assert p.search("anything") == []


def test_search_parses_without_network() -> None:
    """search() routes through _get; stub it so no real HTTP happens."""

    class Stubbed(OpenAlexLiteratureProvider):
        def _get(self, path, params=None):
            assert path == "works" and params["search"] == "residual rl"
            return {"results": [SAMPLE_WORK, SAMPLE_WORK, SAMPLE_WORK]}

    items = Stubbed().search("residual rl", limit=2)
    assert len(items) == 2 and all(isinstance(i, LiteratureItem) for i in items)


def test_search_degrades_on_error() -> None:
    class Failing(OpenAlexLiteratureProvider):
        def _get(self, path, params=None):
            raise OSError("network down")

    assert Failing().search("x") == []  # graceful, no exception


def test_empty_query_returns_empty() -> None:
    assert OpenAlexLiteratureProvider().search("   ") == []


def _work(wid: str, cites: int, refs: list[str] | None = None) -> dict:
    return {
        "id": f"https://openalex.org/{wid}",
        "title": wid,
        "cited_by_count": cites,
        "referenced_works": refs or [],
    }


def test_gather_expands_dedupes_and_ranks() -> None:
    seed = _work("Seed", cites=5, refs=["https://openalex.org/Ref1"])

    class Gathering(OpenAlexLiteratureProvider):
        def _get(self, path, params=None):
            f = (params or {}).get("filter", "")
            if "search" in (params or {}):  # seed search
                return {"results": [seed]}
            if f.startswith("openalex:"):  # references batch
                return {"results": [_work("Ref1", cites=100)]}
            if f.startswith("cites:"):  # citations of the seed
                return {"results": [_work("Cite1", cites=50), seed], "meta": {"next_cursor": None}}
            return {"results": []}

    items = Gathering().gather("graph nets", limit=5, expand=True, seeds=1)
    titles = [i.title for i in items]
    # Seed first (relevance), then expansions by citation count; seed not duplicated.
    assert titles[0] == "Seed"
    assert titles == ["Seed", "Ref1", "Cite1"]


def test_gather_without_expand_is_just_search() -> None:
    class SearchOnly(OpenAlexLiteratureProvider):
        def _get(self, path, params=None):
            return {"results": [_work("A", 1), _work("B", 2)]}

    items = SearchOnly().gather("x", limit=5, expand=False)
    assert {i.title for i in items} == {"A", "B"}


def test_null_provider_gather_offline() -> None:
    assert NullLiteratureProvider().gather("anything") == []


def test_fetch_citations_paginates_and_respects_limit() -> None:
    pages = [
        {"results": [SAMPLE_WORK, SAMPLE_WORK], "meta": {"next_cursor": "c2"}},
        {"results": [SAMPLE_WORK, SAMPLE_WORK], "meta": {"next_cursor": None}},
    ]

    class Paged(OpenAlexLiteratureProvider):
        def __init__(self):
            super().__init__()
            self._i = 0

        def _get(self, path, params=None):
            page = pages[self._i]
            self._i += 1
            return page

    items = Paged().fetch_citations("https://openalex.org/W1", limit=3)
    assert len(items) == 3  # limit enforced across pages
