"""End-to-end (minus the real model): register -> index -> browse -> explain."""

from __future__ import annotations

from pathlib import Path

from dip.container import Container
from dip.core.config import Settings


def test_register_index_and_explain(container: Container, sample_repo: Path, fake_llm) -> None:
    # Register + index.
    project = container.projects.register_project(sample_repo)
    result = container.index.index_project(project.id)

    # calculator.py and pkg/__init__.py indexed; build/ + secret_stuff/ + __pycache__ excluded.
    indexed_paths = {f.relative_path for f in container.store.list_files(project.id)}
    assert "calculator.py" in indexed_paths
    assert "pkg/__init__.py" in indexed_paths
    assert not any(p.startswith("build/") for p in indexed_paths)
    assert not any(p.startswith("secret_stuff/") for p in indexed_paths)
    assert not any(p.startswith("__pycache__/") for p in indexed_paths)
    assert result.symbols_indexed > 0

    # File tree reflects the indexed structure.
    tree = container.repository.get_file_tree(project.id)
    top_level = {c.name for c in tree.children}
    assert "calculator.py" in top_level
    assert "pkg" in top_level

    # Symbols for a file.
    symbols = container.repository.list_symbols(project.id, "calculator.py")
    assert any(s.name == "Calculator" and s.kind.value == "class" for s in symbols)

    # Explain a symbol — workflow returns text plus the exact context sent.
    add_symbol = next(s for s in symbols if s.name == "add")
    explanation = container.explore.explain_symbol(project.id, add_symbol.id)
    assert explanation.text == fake_llm.reply
    assert explanation.model == "fake-model"

    # The model was actually given the selected symbol's source.
    assert fake_llm.last_messages is not None
    user_msg = fake_llm.last_messages[-1].content
    assert "self.total += value" in user_msg
    assert "calculator.py" in user_msg

    # And the returned context package matches what we expect to display.
    region_symbols = {r.symbol for r in explanation.context.source_regions}
    assert "calculator.Calculator.add" in region_symbols


def test_register_is_idempotent_on_same_path(container: Container, sample_repo: Path) -> None:
    p1 = container.projects.register_project(sample_repo)
    p2 = container.projects.register_project(sample_repo)
    assert p1.id == p2.id
    assert len(container.projects.list_projects()) == 1


def test_reindex_clears_previous_symbols(container: Container, sample_repo: Path) -> None:
    project = container.projects.register_project(sample_repo)
    container.index.index_project(project.id)
    first = container.store.count_symbols(project.id)
    container.index.index_project(project.id)
    second = container.store.count_symbols(project.id)
    assert first == second  # no duplication after re-index


def test_persistence_survives_new_container(settings: Settings, sample_repo: Path, fake_llm) -> None:
    c1 = Container.create(settings=settings, llm=fake_llm)
    project = c1.projects.register_project(sample_repo)
    c1.index.index_project(project.id)
    c1.connection.close()

    # A fresh container against the same storage dir sees the persisted project.
    c2 = Container.create(settings=settings, llm=fake_llm)
    projects = c2.projects.list_projects()
    assert len(projects) == 1
    assert projects[0].id == project.id
    assert c2.store.count_symbols(project.id) > 0
