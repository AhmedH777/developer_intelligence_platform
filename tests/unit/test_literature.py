from __future__ import annotations

from dip.core.models import LiteratureItem
from dip.tools.literature import (
    NullLiteratureProvider,
    OpenAlexLiteratureProvider,
    _abstract_snippet,
    _to_item,
)

SAMPLE_WORK = {
    "display_name": "Residual RL for Control",
    "publication_year": 2024,
    "authorships": [
        {"author": {"display_name": "A. Doe"}},
        {"author": {"display_name": "B. Roe"}},
    ],
    "primary_location": {"source": {"display_name": "NeurIPS"}},
    "doi": "https://doi.org/10.1/x",
    "cited_by_count": 42,
    "abstract_inverted_index": {"We": [0], "study": [1], "residual": [2], "RL": [3]},
}


def test_to_item_parses_openalex_work() -> None:
    item = _to_item(SAMPLE_WORK)
    assert item.title == "Residual RL for Control"
    assert item.year == 2024
    assert item.authors == ["A. Doe", "B. Roe"]
    assert item.venue == "NeurIPS"
    assert item.cited_by_count == 42
    assert item.url == "https://doi.org/10.1/x"
    assert item.abstract_snippet == "We study residual RL"


def test_abstract_snippet_orders_by_position_and_truncates() -> None:
    inverted = {"b": [1], "a": [0], "c": [2]}
    assert _abstract_snippet(inverted) == "a b c"
    assert _abstract_snippet({"x": [i for i in range(50)]}, max_words=3).endswith("…")
    assert _abstract_snippet(None) == ""


def test_null_provider_offline() -> None:
    p = NullLiteratureProvider()
    assert p.available is False
    assert p.search("anything") == []


def test_openalex_search_parses_without_network() -> None:
    """search() uses _fetch; we stub it so no real HTTP happens."""

    class StubbedProvider(OpenAlexLiteratureProvider):
        def _fetch(self, url: str) -> dict:
            assert "search=" in url
            return {"results": [SAMPLE_WORK, SAMPLE_WORK, SAMPLE_WORK]}

    items = StubbedProvider().search("residual rl", limit=2)
    assert len(items) == 2
    assert all(isinstance(i, LiteratureItem) for i in items)
    assert items[0].title == "Residual RL for Control"


def test_openalex_search_degrades_on_error() -> None:
    class FailingProvider(OpenAlexLiteratureProvider):
        def _fetch(self, url: str) -> dict:
            raise OSError("network down")

    assert FailingProvider().search("x") == []  # graceful, no exception


def test_openalex_empty_query() -> None:
    assert OpenAlexLiteratureProvider().search("   ") == []
