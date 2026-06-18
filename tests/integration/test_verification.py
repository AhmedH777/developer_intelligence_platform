"""Verification pipeline + completion gating, driven through the implement flow."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dip.container import Container
from dip.core.config import Settings
from dip.core.models import TaskState, VerificationStatus
from dip.llm.client import LLMResponse
from dip.workflows.implement import CompletionBlockedError

PLAN_JSON = json.dumps(
    {
        "goal": "Edit calculator",
        "acceptance_criteria": ["it works"],
        "files_likely_to_change": [{"path": "calculator.py", "reason": "edit"}],
        "files_to_inspect": [{"path": "calculator.py", "reason": "context"}],
    }
)

GOOD_PATCH = json.dumps(
    {
        "summary": "Add subtract",
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
    }
)

BROKEN_PATCH = json.dumps(
    {
        "summary": "Break multiply",
        "edits": [
            {
                "path": "calculator.py",
                "search": "    return a * b\n",
                "replace": "    return a *  # broken syntax\n",
            }
        ],
    }
)


def _llm(patch_json: str):
    class DualLLM:
        def generate(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
            system = messages[0].content.lower()
            return LLMResponse(
                text=(patch_json if "patch" in system else PLAN_JSON), model="scripted", raw={}
            )

    return DualLLM()


@pytest.fixture
def repo_copy(tmp_path: Path, sample_repo: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(sample_repo, dest)
    return dest


def _apply(settings: Settings, repo_copy: Path, patch_json: str):
    container = Container.create(settings=settings, llm=_llm(patch_json))
    project = container.projects.register_project(repo_copy)
    container.index.index_project(project.id)
    task = container.tasks.create_task(project.id, "t", "edit calculator")
    container.plan.generate_plan(task.id)
    container.plan.approve(task.id)
    stored = container.implement.generate_patch(task.id)
    container.implement.apply_patch(task.id, stored.id)
    return container, task.id


def test_passing_verification_allows_accept(settings: Settings, repo_copy: Path) -> None:
    container, task_id = _apply(settings, repo_copy, GOOD_PATCH)
    run = container.verification.verify_task(task_id)

    names = {s.name: s.status for s in run.steps}
    assert names["Python syntax"] == VerificationStatus.PASS
    assert run.status == VerificationStatus.PASS

    # Accept is allowed.
    container.implement.accept(task_id)
    assert container.tasks.get_task(task_id).state == TaskState.DONE


def test_failing_syntax_blocks_completion(settings: Settings, repo_copy: Path) -> None:
    container, task_id = _apply(settings, repo_copy, BROKEN_PATCH)
    run = container.verification.verify_task(task_id)

    syntax = next(s for s in run.steps if s.name == "Python syntax")
    assert syntax.status == VerificationStatus.FAIL
    assert run.status == VerificationStatus.FAIL

    # Accept is blocked while verification fails...
    with pytest.raises(CompletionBlockedError):
        container.implement.accept(task_id)
    # ...but an explicit override is allowed (auditable decision).
    container.implement.accept(task_id, override=True)
    assert container.tasks.get_task(task_id).state == TaskState.DONE


def test_verification_persisted_and_retrievable(settings: Settings, repo_copy: Path) -> None:
    container, task_id = _apply(settings, repo_copy, GOOD_PATCH)
    container.verification.verify_task(task_id)
    latest = container.verification.latest(task_id)
    assert latest is not None
    assert latest.steps  # persisted with steps
