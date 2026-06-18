"""Implement workflow end-to-end with a scripted model (no network).

Operates on a temp copy of the fixture repo so the committed fixture is never
mutated by apply/rollback.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dip.container import Container
from dip.core.config import Settings
from dip.core.models import TaskState
from dip.llm.client import LLMResponse
from dip.workflows.implement import PatchGenerationError

PLAN_JSON = json.dumps(
    {
        "goal": "Add a subtract method to Calculator",
        "acceptance_criteria": ["subtract lowers the running total"],
        "files_to_inspect": [{"path": "calculator.py", "reason": "defines Calculator"}],
        "files_likely_to_change": [{"path": "calculator.py", "reason": "add the method"}],
    }
)

# Search block copied verbatim from the fixture's calculator.py (unique).
PATCH_JSON = json.dumps(
    {
        "summary": "Add Calculator.subtract",
        "rationale": "Mirror add() to support subtraction.",
        "edits": [
            {
                "path": "calculator.py",
                "search": "    def reset(self) -> None:\n        self.total = 0\n",
                "replace": (
                    "    def reset(self) -> None:\n"
                    "        self.total = 0\n\n"
                    "    def subtract(self, value: int) -> int:\n"
                    "        self.total -= value\n"
                    "        return self.total\n"
                ),
            }
        ],
        "risks": [],
    }
)


class DualLLM:
    """Returns plan JSON or patch JSON based on the system prompt."""

    def generate(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
        system = messages[0].content.lower()
        text = PATCH_JSON if "patch" in system else PLAN_JSON
        return LLMResponse(text=text, model="scripted", raw={})


@pytest.fixture
def repo_copy(tmp_path: Path, sample_repo: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(sample_repo, dest)
    return dest


def _prepare(settings: Settings, repo_copy: Path):
    container = Container.create(settings=settings, llm=DualLLM())
    project = container.projects.register_project(repo_copy)
    container.index.index_project(project.id)
    task = container.tasks.create_task(
        project.id, "Subtract", "Add a subtract method to the Calculator class"
    )
    container.plan.generate_plan(task.id)
    container.plan.approve(task.id)
    return container, project.id, task.id


def test_generate_apply_and_rollback(settings: Settings, repo_copy: Path) -> None:
    container, _project_id, task_id = _prepare(settings, repo_copy)
    calc = repo_copy / "calculator.py"
    before = calc.read_text()

    # Generate patch -> PATCH_PROPOSED with a safe preview.
    stored = container.implement.generate_patch(task_id)
    assert container.tasks.get_task(task_id).state == TaskState.PATCH_PROPOSED
    assert stored.preview.safe
    assert "subtract" in stored.preview.file_changes[0].updated

    # The model cannot have written anything yet.
    assert calc.read_text() == before

    # Apply -> file changes on disk, task APPLIED.
    container.implement.apply_patch(task_id, stored.id)
    assert container.tasks.get_task(task_id).state == TaskState.APPLIED
    assert "def subtract" in calc.read_text()

    # Roll back -> file restored exactly, task ROLLED_BACK.
    container.implement.rollback(task_id)
    assert container.tasks.get_task(task_id).state == TaskState.ROLLED_BACK
    assert calc.read_text() == before


def test_apply_then_accept(settings: Settings, repo_copy: Path) -> None:
    container, project_id, task_id = _prepare(settings, repo_copy)
    stored = container.implement.generate_patch(task_id)
    container.implement.apply_patch(task_id, stored.id)

    # New symbol is indexed after apply.
    names = {s.name for s in container.store.search_symbols(project_id, "subtract")}
    assert "subtract" in names

    container.implement.accept(task_id)
    assert container.tasks.get_task(task_id).state == TaskState.DONE


def test_generate_patch_requires_approved_plan(settings: Settings, repo_copy: Path) -> None:
    container = Container.create(settings=settings, llm=DualLLM())
    project = container.projects.register_project(repo_copy)
    container.index.index_project(project.id)
    task = container.tasks.create_task(project.id, "x", "Add subtract to Calculator")
    # No plan approved yet.
    with pytest.raises(PatchGenerationError):
        container.implement.generate_patch(task.id)


def test_unsafe_patch_cannot_be_applied(settings: Settings, repo_copy: Path) -> None:
    """A proposal with a stale search block is stored but blocked from applying."""

    class StalePatchLLM:
        def generate(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
            system = messages[0].content.lower()
            if "patch" in system:
                bad = json.dumps(
                    {
                        "summary": "stale",
                        "edits": [
                            {"path": "calculator.py", "search": "NOT PRESENT", "replace": "x"}
                        ],
                    }
                )
                return LLMResponse(text=bad, model="scripted", raw={})
            return LLMResponse(text=PLAN_JSON, model="scripted", raw={})

    container = Container.create(settings=settings, llm=StalePatchLLM())
    project = container.projects.register_project(repo_copy)
    container.index.index_project(project.id)
    task = container.tasks.create_task(project.id, "x", "Add subtract to Calculator")
    container.plan.generate_plan(task.id)
    container.plan.approve(task.id)

    stored = container.implement.generate_patch(task.id)
    assert not stored.preview.safe
    from dip.tools.patch import PatchError

    with pytest.raises(PatchError):
        container.implement.apply_patch(task.id, stored.id)
