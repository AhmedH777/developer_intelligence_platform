from __future__ import annotations

from dip.core.models import ExperimentProposal
from dip.tools.literature import LiteratureItem, NullLiteratureProvider


def _proposal(novelty="medium", impact="medium", effort="medium") -> ExperimentProposal:
    return ExperimentProposal(
        title="t", hypothesis="h", novelty=novelty, expected_impact=impact, effort=effort
    )


def test_score_objectives() -> None:
    high_nov = _proposal(novelty="high", impact="low", effort="high")
    high_imp = _proposal(novelty="low", impact="high", effort="high")
    easy = _proposal(novelty="low", impact="low", effort="low")

    assert high_nov.score("novelty") == 1.0
    assert high_imp.score("impact") == 1.0
    assert easy.score("feasibility") == 1.0  # low effort -> max feasibility
    # Balanced averages the three signals.
    assert 0.0 <= _proposal().score("balanced") <= 1.0


def test_balanced_ranking_prefers_all_round() -> None:
    strong = _proposal(novelty="high", impact="high", effort="low")
    weak = _proposal(novelty="low", impact="low", effort="high")
    assert strong.score("balanced") > weak.score("balanced")


def test_null_literature_provider_is_offline() -> None:
    provider = NullLiteratureProvider()
    assert provider.available is False
    assert provider.search("anything", limit=5) == []


def test_literature_item_citation() -> None:
    item = LiteratureItem(title="Residual RL", year=2024, authors=["Doe", "Roe"])
    assert "Doe et al." in item.citation
    assert "2024" in item.citation
