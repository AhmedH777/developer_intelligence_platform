"""Skills are retrieved by relevance and injected into the planning context."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dip.container import Container
from dip.core.config import Settings
from dip.llm.client import LLMResponse
from dip.skills.loader import SkillLoader

SKILL_MD = """\
# Add a Calculator Method

How to add a new arithmetic method to the Calculator class.

## Required steps
1. Add the method to calculator.py
2. Mirror the existing add() method.

## Verification commands
- pytest -q
"""

UNRELATED_SKILL = "# Deploy Service\n\nHow to deploy the web service.\n\n## Required steps\n1. Push image.\n"


@pytest.fixture
def repo_copy(tmp_path: Path, sample_repo: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(sample_repo, dest)
    skills = dest / "skills"
    skills.mkdir()
    (skills / "add_calculator_method.md").write_text(SKILL_MD, encoding="utf-8")
    (skills / "deploy_service.md").write_text(UNRELATED_SKILL, encoding="utf-8")
    return dest


def test_retrieve_ranks_relevant_skill_first(repo_copy: Path) -> None:
    loader = SkillLoader()
    hits = loader.retrieve(str(repo_copy), "add a method to the Calculator", limit=1)
    assert hits and hits[0].name == "Add a Calculator Method"


def test_plan_injects_relevant_skill_into_context_and_prompt(
    tmp_path: Path, repo_copy: Path
) -> None:
    captured: dict[str, str] = {}

    class CapturingLLM:
        def generate(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
            captured["user"] = messages[-1].content
            return LLMResponse(
                text=json.dumps({"goal": "x", "files_likely_to_change": []}),
                model="scripted",
                raw={},
            )

    base = Settings(registry_path=tmp_path / "registry.json")
    container = Container.for_repo(repo_copy, base_settings=base, llm=CapturingLLM())
    container.index.index_project(container.project_id)

    task = container.tasks.create_task(
        container.project_id, "feat", "Add a subtract method to the Calculator class"
    )
    stored = container.plan.generate_plan(task.id)

    # The relevant skill is attached to the package and rendered in the prompt;
    # the unrelated deploy skill is not.
    assert any("Add a Calculator Method" in s for s in stored.context.skills)
    assert "Repository skills" in captured["user"]
    assert "Mirror the existing add() method" in captured["user"]
    assert "Deploy Service" not in captured["user"]
