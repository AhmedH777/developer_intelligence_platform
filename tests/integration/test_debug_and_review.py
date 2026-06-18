"""Debug and review workflows end-to-end with a scripted model."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dip.container import Container
from dip.core.config import Settings
from dip.llm.client import LLMResponse

DEBUG_JSON = json.dumps(
    {
        "summary": "multiply divides by zero when b is 0",
        "hypotheses": [
            {"description": "b is zero", "confidence": "high", "evidence": "calculator.py:multiply"}
        ],
        "suggested_inspection": ["print b before dividing"],
        "minimal_fix": "guard against b == 0",
        "regression_test": "test multiply with b=0 raises a clear error",
        "verification_plan": ["pytest -q test_calculator.py"],
    }
)

REVIEW_JSON = json.dumps(
    {
        "summary": "Looks mostly fine; one missing test.",
        "findings": [
            {
                "severity": "warning",
                "category": "missing tests",
                "file_path": "calculator.py",
                "start_line": 1,
                "end_line": 5,
                "title": "No test for subtract",
                "explanation": "subtract has no coverage",
                "recommendation": "add a unit test",
            }
        ],
    }
)

PLAN_JSON = json.dumps(
    {
        "goal": "add subtract",
        "files_likely_to_change": [{"path": "calculator.py", "reason": "edit"}],
        "files_to_inspect": [{"path": "calculator.py", "reason": "ctx"}],
    }
)
PATCH_JSON = json.dumps(
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


class RoutingLLM:
    """Routes to the right canned JSON based on the system prompt."""

    def generate(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
        system = messages[0].content.lower()
        if "debugging assistant" in system:
            text = DEBUG_JSON
        elif "code reviewer" in system:
            text = REVIEW_JSON
        elif "minimal patch" in system:
            text = PATCH_JSON
        else:
            text = PLAN_JSON
        return LLMResponse(text=text, model="scripted", raw={})


@pytest.fixture
def repo_copy(tmp_path: Path, sample_repo: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(sample_repo, dest)
    return dest


def test_debug_classifies_project_frames_and_links_hypotheses(
    settings: Settings, repo_copy: Path
) -> None:
    container = Container.create(settings=settings, llm=RoutingLLM())
    project = container.projects.register_project(repo_copy)
    container.index.index_project(project.id)
    task = container.tasks.create_task(project.id, "bug", "multiply crashes")

    tb = (
        "Traceback (most recent call last):\n"
        f'  File "{repo_copy / "calculator.py"}", line 25, in multiply\n'
        "    return a * b\n"
        '  File "/usr/lib/python3.11/runpy.py", line 87, in _run_code\n'
        "    exec(code)\n"
        "ZeroDivisionError: division by zero\n"
    )
    report = container.debug.analyze(project.id, tb, task_id=task.id)

    # In-project vs external frames classified correctly.
    project_frames = report.project_frames
    assert any(f.relative_path == "calculator.py" for f in project_frames)
    assert all(f.relative_path != "calculator.py" or f.in_project for f in report.frames)
    external = [f for f in report.frames if not f.in_project]
    assert any("runpy.py" in f.file_path for f in external)

    # Hypotheses came through and the report persisted.
    assert report.analysis.hypotheses[0].confidence == "high"
    assert report.exception_type == "ZeroDivisionError"
    assert container.debug.latest(task.id) is not None

    # Context included source around the in-project frame.
    assert any(r.relative_path == "calculator.py" for r in report.context.source_regions)


def test_review_latest_patch_produces_findings(settings: Settings, repo_copy: Path) -> None:
    container = Container.create(settings=settings, llm=RoutingLLM())
    project = container.projects.register_project(repo_copy)
    container.index.index_project(project.id)
    task = container.tasks.create_task(project.id, "feat", "add subtract")
    container.plan.generate_plan(task.id)
    container.plan.approve(task.id)
    container.implement.generate_patch(task.id)

    review = container.review.review_latest_patch(task.id)
    assert review.result.findings
    finding = review.result.findings[0]
    assert finding.file_path == "calculator.py"
    assert finding.severity == "warning"
    # The diff was included as the review target.
    assert "subtract" in review.context.user_request
    assert container.review.latest(task.id) is not None


def test_review_without_patch_raises(settings: Settings, repo_copy: Path) -> None:
    container = Container.create(settings=settings, llm=RoutingLLM())
    project = container.projects.register_project(repo_copy)
    container.index.index_project(project.id)
    task = container.tasks.create_task(project.id, "x", "nothing yet")
    from dip.workflows.review import ReviewError

    with pytest.raises(ReviewError):
        container.review.review_latest_patch(task.id)
