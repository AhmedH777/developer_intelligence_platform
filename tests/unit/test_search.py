from __future__ import annotations

from pathlib import Path

from dip.container import Container


def _index(container: Container, sample_repo: Path) -> str:
    project = container.projects.register_project(sample_repo)
    container.index.index_project(project.id)
    return project.id


def test_exact_symbol_match_ranks_first(container: Container, sample_repo: Path) -> None:
    project_id = _index(container, sample_repo)
    results = container.repository.search(project_id, "add")
    assert results, "expected at least one result for 'add'"
    top = results[0]
    assert top.kind == "symbol"
    assert top.symbol is not None and top.symbol.name == "add"
    assert "exact symbol name match" in top.reason


def test_file_name_match(container: Container, sample_repo: Path) -> None:
    project_id = _index(container, sample_repo)
    results = container.repository.search(project_id, "calculator")
    file_hits = [r for r in results if r.kind == "file"]
    assert any(r.relative_path == "calculator.py" for r in file_hits)


def test_empty_query_returns_nothing(container: Container, sample_repo: Path) -> None:
    project_id = _index(container, sample_repo)
    assert container.repository.search(project_id, "   ") == []
