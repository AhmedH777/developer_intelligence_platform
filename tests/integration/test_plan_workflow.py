"""Plan workflow end-to-end with a scripted model (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dip.container import Container
from dip.core.config import Settings
from dip.core.models import TaskState
from dip.llm.client import LLMResponse
from dip.workflows.plan import PlanGenerationError

PLAN_JSON = json.dumps(
    {
        "goal": "Add a subtract method to Calculator",
        "acceptance_criteria": ["Calculator.subtract(n) lowers the total by n"],
        "relevant_architecture": "Calculator holds a running total in calculator.py",
        "files_to_inspect": [{"path": "calculator.py", "reason": "defines Calculator"}],
        "files_likely_to_change": [
            {"path": "calculator.py", "reason": "add the method here"},
            {"path": "made_up_helpers.py", "reason": "hallucinated path"},
        ],
        "tests_to_add": ["test subtract reduces the total"],
        "risks": ["none significant"],
        "assumptions": ["integer math only"],
        "open_questions": [],
    }
)


class PlanLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.last_messages = None

    def generate(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
        self.last_messages = messages
        return LLMResponse(text=self.reply, model="scripted", raw={})


def _make(settings: Settings, sample_repo: Path, reply: str):
    container = Container.create(settings=settings, llm=PlanLLM(reply))
    project = container.projects.register_project(sample_repo)
    container.index.index_project(project.id)
    return container, project.id


def test_generate_plan_grounds_files_and_awaits_approval(
    settings: Settings, sample_repo: Path
) -> None:
    container, project_id = _make(settings, sample_repo, PLAN_JSON)
    task = container.tasks.create_task(
        project_id, "Subtract", "Add a subtract method to the Calculator class"
    )

    stored = container.plan.generate_plan(task.id)

    # Task is now awaiting approval.
    assert container.tasks.get_task(task.id).state == TaskState.PLANNED

    # Plan content round-tripped through SQLite.
    assert stored.plan.goal.startswith("Add a subtract")
    assert "calculator.py" in stored.grounding.grounded_paths
    assert "made_up_helpers.py" in stored.grounding.ungrounded_paths
    assert not stored.grounding.all_grounded

    # Per-ref existence flags set during grounding.
    change_refs = {ref.path: ref.exists for ref in stored.plan.files_likely_to_change}
    assert change_refs["calculator.py"] is True
    assert change_refs["made_up_helpers.py"] is False

    # The model received real repository evidence (Calculator source).
    user_msg = container.plan._llm.last_messages[-1].content  # type: ignore[attr-defined]
    assert "class Calculator" in user_msg

    # Plan is retrievable as the latest plan for the task.
    latest = container.plan.get_latest_plan(task.id)
    assert latest is not None and latest.id == stored.id


def test_approve_and_reject_transitions(settings: Settings, sample_repo: Path) -> None:
    container, project_id = _make(settings, sample_repo, PLAN_JSON)
    task = container.tasks.create_task(project_id, "Subtract", "Add subtract to Calculator")
    container.plan.generate_plan(task.id)

    approved = container.plan.approve(task.id)
    assert approved.state == TaskState.PLAN_APPROVED

    # A fresh task can be rejected then re-planned.
    task2 = container.tasks.create_task(project_id, "Again", "Add subtract to Calculator")
    container.plan.generate_plan(task2.id)
    container.plan.reject(task2.id, "Too broad")
    assert container.tasks.get_task(task2.id).state == TaskState.PLAN_REJECTED
    container.plan.generate_plan(task2.id)  # re-plan after rejection
    assert container.tasks.get_task(task2.id).state == TaskState.PLANNED


def test_invalid_model_output_fails_task(settings: Settings, sample_repo: Path) -> None:
    container, project_id = _make(settings, sample_repo, "this is not json")
    task = container.tasks.create_task(project_id, "Bad", "Add subtract to Calculator")
    with pytest.raises(PlanGenerationError):
        container.plan.generate_plan(task.id)
    assert container.tasks.get_task(task.id).state == TaskState.FAILED
