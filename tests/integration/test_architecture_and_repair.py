"""Architecture verification step + bounded repair loop."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dip.container import Container
from dip.core.config import Settings
from dip.core.models import VerificationStatus
from dip.llm.client import LLMResponse


@pytest.fixture
def repo_copy(tmp_path: Path, sample_repo: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(sample_repo, dest)
    return dest


# --- Architecture: project-wide check on the real backend -------------------
def test_project_import_index_and_no_violations_on_clean_backend(
    settings: Settings,
) -> None:
    # Index this very repository; dip/ must not import streamlit.
    container = Container.create(settings=settings)
    project = container.projects.register_project(".")
    container.index.index_project(project.id)

    imports = container.store.list_imports(project.id)
    assert any(module == "streamlit" for _, module in imports)  # ui/ imports it
    violations = container.architecture.check_project(project.id)
    # The rule applies only to dip/, which is UI-agnostic, so there are none.
    assert violations == []


def test_architecture_violation_detected_in_changed_file(
    settings: Settings, repo_copy: Path
) -> None:
    container = Container.create(settings=settings)
    # Simulate a backend file that illegally imports streamlit.
    (repo_copy / "dip").mkdir(parents=True, exist_ok=True)
    (repo_copy / "dip" / "leak.py").write_text("import streamlit\n", encoding="utf-8")
    project = container.projects.register_project(repo_copy)
    container.index.index_project(project.id)

    violations = container.architecture.check_files(str(repo_copy), ["dip/leak.py"])
    assert violations and violations[0].imported_module == "streamlit"


# --- Bounded repair ---------------------------------------------------------
PLAN_JSON = json.dumps(
    {
        "goal": "edit calculator",
        "files_likely_to_change": [{"path": "calculator.py", "reason": "edit"}],
        "files_to_inspect": [{"path": "calculator.py", "reason": "ctx"}],
    }
)
# This patch introduces a syntax error -> verification fails.
BREAKING_PATCH = json.dumps(
    {
        "summary": "break",
        "edits": [{"path": "calculator.py", "search": "    return a * b\n", "replace": "    return a *  # broken\n"}],
    }
)
# The repair fixes the syntax error.
REPAIR_FIX = json.dumps(
    {
        "hypothesis": "the multiply body has a syntax error and must be restored",
        "summary": "restore multiply body",
        "edits": [{"path": "calculator.py", "search": "    return a *  # broken\n", "replace": "    return a * b\n"}],
    }
)


def _container(settings, repo, patch_json, repair_json, max_attempts=2):
    settings.safety.max_repair_attempts = max_attempts

    class LLM:
        def generate(self, m, *, temperature=None, max_tokens=None):
            s = m[0].content.lower()
            if "failing change" in s:  # repair system prompt
                text = repair_json
            elif "minimal patch" in s:
                text = patch_json
            else:
                text = PLAN_JSON
            return LLMResponse(text=text, model="scripted", raw={})

    container = Container.create(settings=settings, llm=LLM())
    project = container.projects.register_project(repo)
    container.index.index_project(project.id)
    task = container.tasks.create_task(project.id, "t", "edit calculator")
    container.plan.generate_plan(task.id)
    container.plan.approve(task.id)
    stored = container.implement.generate_patch(task.id)
    container.implement.apply_patch(task.id, stored.id)
    container.verification.verify_task(task.id)  # fails (syntax)
    return container, task.id


def test_repair_fixes_failing_verification(settings: Settings, repo_copy: Path) -> None:
    container, task_id = _container(settings, repo_copy, BREAKING_PATCH, REPAIR_FIX)
    assert container.verification.latest(task_id).status == VerificationStatus.FAIL

    result = container.repair.run(task_id)
    assert result.status == "fixed"
    assert container.verification.latest(task_id).status != VerificationStatus.FAIL
    assert "def subtract" not in (repo_copy / "calculator.py").read_text()  # untouched logic
    assert "return a * b" in (repo_copy / "calculator.py").read_text()


def test_repair_stops_on_repeated_hypothesis(settings: Settings, repo_copy: Path) -> None:
    # Repair keeps proposing a stale (non-matching) edit with the SAME hypothesis.
    stale_repair = json.dumps(
        {
            "hypothesis": "same idea every time",
            "summary": "noop",
            "edits": [{"path": "calculator.py", "search": "NONEXISTENT", "replace": "x"}],
        }
    )
    container, task_id = _container(settings, repo_copy, BREAKING_PATCH, stale_repair, max_attempts=3)
    result = container.repair.run(task_id)
    # First attempt: stale -> not applied, continue. Second: same hypothesis -> stop.
    assert result.status == "stopped"
    assert any("repeated" in a.note.lower() for a in result.attempts)


def test_repair_requires_applied_state(settings: Settings, repo_copy: Path) -> None:
    container = Container.create(settings=settings)
    project = container.projects.register_project(repo_copy)
    container.index.index_project(project.id)
    task = container.tasks.create_task(project.id, "t", "x")
    result = container.repair.run(task.id)
    assert result.status == "failed"
