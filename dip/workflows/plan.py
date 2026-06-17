"""Plan workflow: turn a task request into a grounded, structured plan.

Steps: move the task to INVESTIGATING, compile repository evidence, ask the model
for a structured plan (with one repair attempt), validate that cited files exist
in the index, persist the plan, and move the task to PLANNED (awaiting approval)
or FAILED. The user approves or rejects via :meth:`approve` / :meth:`reject`.
"""

from __future__ import annotations

import uuid

from dip.context.compiler import ContextCompiler
from dip.core.models import (
    ImplementationPlan,
    PlanFileRef,
    PlanGrounding,
    StoredPlan,
    Task,
    TaskState,
)
from dip.core.tasks import TaskService
from dip.llm.client import LLMClient
from dip.llm.prompts import build_plan_messages
from dip.llm.structured import generate_structured
from dip.storage.repo import Store


class PlanWorkflow:
    def __init__(
        self,
        store: Store,
        tasks: TaskService,
        compiler: ContextCompiler,
        llm: LLMClient,
    ) -> None:
        self._store = store
        self._tasks = tasks
        self._compiler = compiler
        self._llm = llm

    def generate_plan(self, task_id: str) -> StoredPlan:
        task = self._tasks.get_task(task_id)
        # Re-planning is allowed from PLAN_REJECTED/FAILED; both transition back
        # through INVESTIGATING.
        if task.state in (TaskState.NEW, TaskState.PLAN_REJECTED, TaskState.FAILED):
            self._tasks.transition(task_id, TaskState.INVESTIGATING, "Investigating repository")

        context = self._compiler.build_plan_context(task.project_id, task.request)
        self._tasks.record_event(
            task_id,
            "context_compiled",
            f"Compiled {len(context.source_regions)} evidence region(s), "
            f"~{context.token_estimate} tokens.",
        )

        messages = build_plan_messages(context)
        result = generate_structured(self._llm, messages, ImplementationPlan)

        if not result.ok or result.value is None:
            self._tasks.transition(
                task_id,
                TaskState.FAILED,
                f"Plan generation failed: {result.error}",
                {"raw_response": result.raw_text[:2000]},
            )
            raise PlanGenerationError(result.error or "Unknown plan generation error")

        plan = result.value
        grounding = self._validate_grounding(task, plan)

        stored = StoredPlan(
            id=str(uuid.uuid4()),
            task_id=task_id,
            plan=plan,
            grounding=grounding,
            context=context,
            model=result.model,
            raw_response=result.raw_text,
            repaired=result.repaired,
        )
        self._store.insert_plan(stored)

        msg = "Plan generated."
        if grounding.ungrounded_paths:
            msg += f" {len(grounding.ungrounded_paths)} cited path(s) not found in the index."
        self._tasks.transition(task_id, TaskState.PLANNED, msg, {"plan_id": stored.id})
        return stored

    def approve(self, task_id: str) -> Task:
        return self._tasks.transition(task_id, TaskState.PLAN_APPROVED, "Plan approved by user")

    def reject(self, task_id: str, reason: str | None = None) -> Task:
        return self._tasks.transition(
            task_id, TaskState.PLAN_REJECTED, reason or "Plan rejected by user"
        )

    def get_latest_plan(self, task_id: str) -> StoredPlan | None:
        return self._store.get_latest_plan(task_id)

    # ----- internals --------------------------------------------------------
    def _validate_grounding(self, task: Task, plan: ImplementationPlan) -> PlanGrounding:
        """Mark each cited file as existing in the index or not (hallucination check)."""

        grounded: list[str] = []
        ungrounded: list[str] = []
        for ref in [*plan.files_to_inspect, *plan.files_likely_to_change]:
            exists = self._store.get_file_by_path(task.project_id, ref.path) is not None
            ref.exists = exists
            (grounded if exists else ungrounded).append(ref.path)
        return PlanGrounding(
            grounded_paths=_dedupe(grounded),
            ungrounded_paths=_dedupe(ungrounded),
        )


class PlanGenerationError(RuntimeError):
    pass


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


# Re-export so callers can reference the model ref type conveniently.
__all__ = ["PlanWorkflow", "PlanGenerationError", "PlanFileRef"]
