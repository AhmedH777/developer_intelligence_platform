from __future__ import annotations

from pathlib import Path

from dip.container import Container


def _index(container: Container, sample_repo: Path) -> str:
    project = container.projects.register_project(sample_repo)
    container.index.index_project(project.id)
    return project.id


def test_explain_context_includes_symbol_and_enclosing_scope(
    container: Container, sample_repo: Path
) -> None:
    project_id = _index(container, sample_repo)
    add = next(
        s
        for s in container.store.search_symbols(project_id, "add")
        if s.name == "add"
    )
    context = container.compiler.build_explain_context(project_id, add)

    reasons = {r.reason for r in context.source_regions}
    assert "selected symbol" in reasons
    assert "enclosing scope of selected symbol" in reasons

    primary = next(r for r in context.source_regions if r.reason == "selected symbol")
    assert "self.total += value" in primary.content
    assert context.token_estimate > 0
    assert context.char_estimate == sum(len(r.content) for r in context.source_regions)


def test_budget_omits_enclosing_scope_when_tiny(
    container: Container, sample_repo: Path
) -> None:
    project_id = _index(container, sample_repo)
    add = next(
        s
        for s in container.store.search_symbols(project_id, "add")
        if s.name == "add"
    )
    container.compiler._char_budget = 5  # force the budget to bite
    context = container.compiler.build_explain_context(project_id, add)
    reasons = {r.reason for r in context.source_regions}
    assert "selected symbol" in reasons  # primary always included
    assert "enclosing scope of selected symbol" not in reasons
    assert any("budget" in note for note in context.notes)
