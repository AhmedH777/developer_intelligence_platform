"""Research Scout end-to-end with a scripted model."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dip.container import Container
from dip.core.config import Settings
from dip.core.models import MemoryCategory, TaskState
from dip.llm.client import LLMResponse

PROPOSALS = json.dumps(
    {
        "summary": "Two experiments to improve the calculator.",
        "proposals": [
            {
                "title": "Add a subtract op",
                "hypothesis": "A subtract method broadens coverage",
                "method": "Add Calculator.subtract mirroring add",
                "affected_paths": [{"path": "calculator.py", "reason": "defines Calculator"}],
                "variants": ["in-place vs functional"],
                "evaluation": "unit tests pass",
                "baselines": ["current add()"],
                "effort": "low",
                "novelty": "low",
                "expected_impact": "medium",
            },
            {
                "title": "Vectorized batch compute",
                "hypothesis": "Batch ops speed up large workloads",
                "method": "Add a vectorized path in a new module",
                "affected_paths": [{"path": "made_up_vector.py", "reason": "new file"}],
                "evaluation": "benchmark throughput",
                "effort": "high",
                "novelty": "high",
                "expected_impact": "high",
            },
        ],
    }
)


class ScoutLLM:
    def generate(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
        self.last = messages
        return LLMResponse(text=PROPOSALS, model="scripted", raw={})


@pytest.fixture
def repo_copy(tmp_path: Path, sample_repo: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(sample_repo, dest)
    return dest


def _container(settings: Settings, repo_copy: Path):
    llm = ScoutLLM()
    container = Container.create(settings=settings, llm=llm)
    project = container.projects.register_project(repo_copy)
    container.index.index_project(project.id)
    return container, project.id, llm


def test_propose_ranks_and_grounds(settings: Settings, repo_copy: Path) -> None:
    container, project_id, _ = _container(settings, repo_copy)
    run = container.research.propose(project_id, direction="improve the calculator")

    # Grounding: calculator.py exists, made_up_vector.py does not.
    assert "calculator.py" in run.grounded_paths
    assert "made_up_vector.py" in run.ungrounded_paths

    # Balanced ranking: the high/high/high-ish proposal outranks the low-novelty one.
    assert run.proposals[0].title == "Vectorized batch compute"

    # Persisted + retrievable.
    assert container.research.latest(project_id).id == run.id


def test_objective_changes_ranking(settings: Settings, repo_copy: Path) -> None:
    container, project_id, _ = _container(settings, repo_copy)
    run = container.research.propose(project_id, direction="x", objective="feasibility")
    # Feasibility favors the low-effort subtract proposal.
    assert run.proposals[0].title == "Add a subtract op"


def test_capability_digest_and_memory_in_prompt(settings: Settings, repo_copy: Path) -> None:
    container, project_id, llm = _container(settings, repo_copy)
    container.memory.add(
        project_id, MemoryCategory.KNOWN_FAILURE, "Calculator overflow on huge ints."
    )
    container.research.propose(project_id, direction="calculator robustness")

    user_msg = llm.last[-1].content
    assert "capability digest" in user_msg.lower()
    assert "class Calculator" in user_msg  # digest lists real symbols
    assert "overflow" in user_msg  # known-failure memory surfaced


def test_promote_to_task_creates_task(settings: Settings, repo_copy: Path) -> None:
    container, project_id, _ = _container(settings, repo_copy)
    run = container.research.propose(project_id, direction="improve the calculator")
    task = container.research.promote_to_task(project_id, run.id, 0)

    assert task.state == TaskState.NEW
    assert task.title == run.proposals[0].title
    assert "Method:" in task.request
    # The task is listed and linked via an event.
    assert any(t.id == task.id for t in container.tasks.list_tasks(project_id))
    assert any(e.event_type == "research" for e in container.tasks.list_events(task.id))


def test_literature_enabled_populates_run_and_prompt(
    settings: Settings, repo_copy: Path
) -> None:
    from dip.core.config import ResearchSettings
    from dip.tools.literature import OpenAlexLiteratureProvider

    settings.research = ResearchSettings(literature=True)
    container, project_id, llm = _container(settings, repo_copy)
    assert isinstance(container.literature, OpenAlexLiteratureProvider)

    # Stub the HTTP layer so no real network call happens.
    container.literature._get = lambda path, params=None: {  # type: ignore[method-assign]
        "results": [
            {
                "title": "Residual RL for Driving",
                "publication_year": 2025,
                "authorships": [{"author": {"display_name": "A. Doe"}}],
                "primary_location": {"source": {"display_name": "CoRL"}},
                "doi": "https://doi.org/10.1/y",
                "cited_by_count": 7,
            }
        ]
    }

    run = container.research.propose(project_id, direction="residual rl sample efficiency")
    assert run.literature and run.literature[0].title == "Residual RL for Driving"
    # The citation was offered to the model in the prompt.
    assert "Residual RL for Driving" in llm.last[-1].content


def test_direction_from_repo_config(tmp_path: Path, repo_copy: Path) -> None:
    (repo_copy / ".devintel.yaml").write_text(
        "research:\n  direction: improve sample efficiency\n  max_proposals: 3\n",
        encoding="utf-8",
    )
    base = Settings(registry_path=tmp_path / "registry.json")
    container = Container.for_repo(repo_copy, base_settings=base, llm=ScoutLLM())
    container.index.index_project(container.project_id)
    run = container.research.propose(container.project_id)  # no explicit direction
    assert run.direction == "improve sample efficiency"
