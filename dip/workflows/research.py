"""Research Scout: propose grounded experiments for a repo, and promote them.

Given the repo's capability digest, a research direction, relevant memory and
skills (and optionally literature), the model proposes ranked experiments. An
accepted proposal becomes a Task that flows into the existing plan → patch →
verify pipeline, closing the loop from idea to implemented experiment.
"""

from __future__ import annotations

import uuid

from dip.context.compiler import ContextCompiler
from dip.core.config import Settings
from dip.core.models import (
    ResearchProposalSet,
    StoredResearchRun,
    Task,
)
from dip.core.tasks import TaskService
from dip.llm.client import LLMClient
from dip.llm.prompts import build_research_messages
from dip.llm.structured import generate_structured
from dip.repository.repository_service import RepositoryService
from dip.storage.repo import Store
from dip.tools.literature import LiteratureProvider, NullLiteratureProvider


class ResearchError(RuntimeError):
    pass


class ResearchWorkflow:
    def __init__(
        self,
        store: Store,
        tasks: TaskService,
        repository: RepositoryService,
        compiler: ContextCompiler,
        llm: LLMClient,
        settings: Settings,
        memory=None,
        skills=None,
        literature: LiteratureProvider | None = None,
    ) -> None:
        self._store = store
        self._tasks = tasks
        self._repo = repository
        self._compiler = compiler
        self._llm = llm
        self._settings = settings
        self._memory = memory
        self._skills = skills
        self._literature = literature or NullLiteratureProvider()

    def propose(
        self, project_id: str, direction: str | None = None, objective: str | None = None
    ) -> StoredResearchRun:
        project = self._store.get_project(project_id)
        if project is None:
            raise ResearchError(f"Unknown project: {project_id}")

        cfg = self._settings.research
        direction = (direction or cfg.direction or "").strip()
        objective = objective or cfg.objective
        query = direction or "promising research directions for this repository"

        digest = self._repo.capability_digest(project_id)
        memory_labels = (
            [m.label for m in self._memory.retrieve(project_id, query)] if self._memory else []
        )
        skill_briefs: list[str] = []
        if self._skills is not None:
            from dip.skills.loader import format_skill_brief

            skill_briefs = [
                format_skill_brief(s) for s in self._skills.retrieve(project.root_path, query)
            ]
        literature = self._literature.search(query, limit=cfg.literature_max)

        context = self._compiler.build_research_context(
            direction, digest, memory_items=memory_labels, skill_items=skill_briefs
        )
        messages = build_research_messages(
            context, direction, digest, literature=literature, max_proposals=cfg.max_proposals
        )
        result = generate_structured(self._llm, messages, ResearchProposalSet)
        if not result.ok or result.value is None:
            raise ResearchError(f"Proposal generation failed: {result.error}")

        proposals = list(result.value.proposals)
        grounded, ungrounded = self._validate_grounding(project_id, proposals)
        # Deterministic ranking by the chosen objective (stable for ties by title).
        proposals.sort(key=lambda p: (-p.score(objective), p.title))

        run = StoredResearchRun(
            id=str(uuid.uuid4()),
            project_id=project_id,
            direction=direction,
            objective=objective,
            summary=result.value.summary,
            proposals=proposals,
            grounded_paths=grounded,
            ungrounded_paths=ungrounded,
            literature=literature,
            context=context,
            model=result.model,
            raw_response=result.raw_text,
            repaired=result.repaired,
        )
        self._store.insert_research_run(run)
        return run

    def latest(self, project_id: str) -> StoredResearchRun | None:
        return self._store.get_latest_research_run(project_id)

    def promote_to_task(self, project_id: str, run_id: str, index: int) -> Task:
        run = self._store.get_research_run(run_id)
        if run is None or not (0 <= index < len(run.proposals)):
            raise ResearchError("Unknown proposal.")
        p = run.proposals[index]
        request = (
            f"{p.hypothesis}\n\n"
            f"Method: {p.method}\n\n"
            f"Evaluation: {p.evaluation}"
            + (f"\n\nVariants: {', '.join(p.variants)}" if p.variants else "")
        )
        task = self._tasks.create_task(project_id, title=p.title, request=request)
        self._tasks.record_event(
            task.id, "research", f"Promoted from research run {run_id}", {"run_id": run_id}
        )
        return task

    # ----- internals --------------------------------------------------------
    def _validate_grounding(self, project_id: str, proposals) -> tuple[list[str], list[str]]:
        grounded: list[str] = []
        ungrounded: list[str] = []
        for proposal in proposals:
            for ref in proposal.affected_paths:
                exists = self._store.get_file_by_path(project_id, ref.path) is not None
                ref.exists = exists
                (grounded if exists else ungrounded).append(ref.path)
        return _dedupe(grounded), _dedupe(ungrounded)


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
