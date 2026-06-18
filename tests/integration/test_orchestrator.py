"""Auto-pilot orchestrator: gated advance through the full pipeline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dip.container import Container
from dip.core.config import Settings
from dip.core.models import TaskState
from dip.llm.client import LLMResponse

PLAN_JSON = json.dumps(
    {
        "goal": "add subtract",
        "files_likely_to_change": [{"path": "calculator.py", "reason": "edit"}],
        "files_to_inspect": [{"path": "calculator.py", "reason": "ctx"}],
    }
)
GOOD_PATCH = json.dumps(
    {
        "summary": "Add subtract",
        "edits": [
            {
                "path": "calculator.py",
                "search": "    def reset(self) -> None:\n        self.total = 0\n",
                "replace": "    def reset(self) -> None:\n        self.total = 0\n\n    def subtract(self, v):\n        return v\n",
            }
        ],
    }
)
BREAKING_PATCH = json.dumps(
    {
        "summary": "break",
        "edits": [{"path": "calculator.py", "search": "    return a * b\n", "replace": "    return a *  # broken\n"}],
    }
)
REPAIR_FIX = json.dumps(
    {
        "hypothesis": "restore multiply body",
        "summary": "fix syntax",
        "edits": [{"path": "calculator.py", "search": "    return a *  # broken\n", "replace": "    return a * b\n"}],
    }
)
BAD_REPAIR = json.dumps(
    {"hypothesis": "no idea", "summary": "noop", "edits": [{"path": "calculator.py", "search": "ZZZ", "replace": "x"}]}
)


def _llm(patch_json: str, repair_json: str = REPAIR_FIX):
    class LLM:
        def generate(self, m, *, temperature=None, max_tokens=None) -> LLMResponse:
            s = m[0].content.lower()
            text = repair_json if "failing change" in s else patch_json if "minimal patch" in s else PLAN_JSON
            return LLMResponse(text=text, model="scripted", raw={})

    return LLM()


@pytest.fixture
def repo_copy(tmp_path: Path, sample_repo: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(sample_repo, dest)
    return dest


def _setup(settings: Settings, repo_copy: Path, patch_json: str, repair_json: str = REPAIR_FIX):
    container = Container.create(settings=settings, llm=_llm(patch_json, repair_json))
    project = container.projects.register_project(repo_copy)
    container.index.index_project(project.id)
    task = container.tasks.create_task(project.id, "t", "Add a subtract method to Calculator")
    return container, task.id


def test_advance_stops_at_plan_then_patch_gate(settings: Settings, repo_copy: Path) -> None:
    container, task_id = _setup(settings, repo_copy, GOOD_PATCH)

    # From NEW: auto-plan, then stop at the plan gate.
    r1 = container.orchestrator.advance(task_id)
    assert r1.stopped == "plan_approval"
    assert container.tasks.get_task(task_id).state == TaskState.PLANNED

    # Approve the plan, advance: auto-generate patch, stop at the patch gate.
    container.plan.approve(task_id)
    r2 = container.orchestrator.advance(task_id)
    assert r2.stopped == "patch_approval"
    assert container.tasks.get_task(task_id).state == TaskState.PATCH_PROPOSED


def test_advance_after_apply_verifies_and_accepts(settings: Settings, repo_copy: Path) -> None:
    container, task_id = _setup(settings, repo_copy, GOOD_PATCH)
    container.orchestrator.advance(task_id)
    container.plan.approve(task_id)
    container.orchestrator.advance(task_id)

    # Approve (apply) the patch, then advance: verify -> accept -> DONE.
    proposal = container.implement.get_latest_proposal(task_id)
    container.implement.apply_patch(task_id, proposal.id)
    result = container.orchestrator.advance(task_id)
    assert result.stopped == "done"
    assert container.tasks.get_task(task_id).state == TaskState.DONE
    assert any(s.action == "accept" for s in result.steps)


def test_advance_auto_repairs_failing_patch(settings: Settings, repo_copy: Path) -> None:
    container, task_id = _setup(settings, repo_copy, BREAKING_PATCH, REPAIR_FIX)
    container.orchestrator.advance(task_id)
    container.plan.approve(task_id)
    container.orchestrator.advance(task_id)
    proposal = container.implement.get_latest_proposal(task_id)
    container.implement.apply_patch(task_id, proposal.id)

    result = container.orchestrator.advance(task_id)
    assert any(s.action == "repair" for s in result.steps)
    assert result.stopped == "done"
    assert container.tasks.get_task(task_id).state == TaskState.DONE


def test_advance_blocks_when_repair_cannot_fix(settings: Settings, repo_copy: Path) -> None:
    container, task_id = _setup(settings, repo_copy, BREAKING_PATCH, BAD_REPAIR)
    container.orchestrator.advance(task_id)
    container.plan.approve(task_id)
    container.orchestrator.advance(task_id)
    proposal = container.implement.get_latest_proposal(task_id)
    container.implement.apply_patch(task_id, proposal.id)

    result = container.orchestrator.advance(task_id)
    assert result.stopped == "blocked"
    assert container.tasks.get_task(task_id).state == TaskState.APPLIED  # not DONE


def test_ungated_runs_end_to_end(settings: Settings, repo_copy: Path) -> None:
    # With no gates, a single advance should drive a clean task to DONE.
    settings.orchestrator.gates = []
    container, task_id = _setup(settings, repo_copy, GOOD_PATCH)
    result = container.orchestrator.advance(task_id)
    assert result.stopped == "done"
    assert container.tasks.get_task(task_id).state == TaskState.DONE
    actions = [s.action for s in result.steps]
    assert actions[:4] == ["plan", "approve_plan", "patch", "apply"]
