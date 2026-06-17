"""Memory CRUD, retrieval, and injection into plan context."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dip.container import Container
from dip.core.config import Settings
from dip.core.models import MemoryCategory
from dip.llm.client import LLMResponse


def _project(container: Container, sample_repo: Path) -> str:
    return container.projects.register_project(sample_repo).id


def test_memory_crud_and_lifecycle(container: Container, sample_repo: Path) -> None:
    project_id = _project(container, sample_repo)
    item = container.memory.add(
        project_id, MemoryCategory.ARCHITECTURE_DECISION, "Use Calculator for all math."
    )
    assert item.enabled and item.source_task_id is None

    container.memory.update_content(item.id, "Use Calculator for arithmetic.", confidence=0.9)
    container.memory.set_enabled(item.id, False)
    reloaded = container.memory.list(project_id)[0]
    assert reloaded.content == "Use Calculator for arithmetic."
    assert reloaded.confidence == 0.9
    assert reloaded.enabled is False

    container.memory.delete(item.id)
    assert container.memory.list(project_id) == []


def test_retrieve_matches_keywords_and_skips_disabled(container: Container, sample_repo: Path) -> None:
    project_id = _project(container, sample_repo)
    container.memory.add(project_id, MemoryCategory.PROJECT_FACT, "The Calculator keeps a total.")
    container.memory.add(project_id, MemoryCategory.PROJECT_FACT, "Logging uses structlog.")
    disabled = container.memory.add(
        project_id, MemoryCategory.PROJECT_FACT, "Calculator is deprecated."
    )
    container.memory.set_enabled(disabled.id, False)

    hits = container.memory.retrieve(project_id, "add a method to the Calculator total")
    contents = [h.content for h in hits]
    assert "The Calculator keeps a total." in contents
    assert "Logging uses structlog." not in contents  # no keyword overlap
    assert "Calculator is deprecated." not in contents  # disabled


def test_plan_context_includes_relevant_memory(settings: Settings, sample_repo: Path) -> None:
    captured = {}

    class CapturingLLM:
        def generate(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
            captured["user"] = messages[-1].content
            return LLMResponse(
                text=json.dumps({"goal": "x", "files_likely_to_change": []}),
                model="scripted",
                raw={},
            )

    container = Container.create(settings=settings, llm=CapturingLLM())
    project = container.projects.register_project(sample_repo)
    container.index.index_project(project.id)
    container.memory.add(
        project.id, MemoryCategory.WORKFLOW_RULE, "Calculator changes need a regression test."
    )

    task = container.tasks.create_task(project.id, "feat", "Add a method to Calculator")
    stored = container.plan.generate_plan(task.id)

    # Memory surfaced into the package and the prompt.
    assert any("regression test" in m for m in stored.context.memory_items)
    assert "Project memory" in captured["user"]
    assert "regression test" in captured["user"]
