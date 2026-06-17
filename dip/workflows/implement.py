"""Implement workflow: generate, apply, and roll back a patch for a task.

Requires an approved plan. Generates a structured search/replace patch, computes
a safe preview (path checks + exact-match validation), and persists it for
approval. The user applies or rejects; applying snapshots the files first so the
change is reversible. Re-indexing after a successful apply keeps the symbol index
consistent with the new source.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from dip.context.compiler import ContextCompiler
from dip.core.models import (
    PatchApplication,
    PatchProposal,
    StoredPatchProposal,
    TaskState,
)
from dip.core.tasks import TaskService
from dip.llm.client import LLMClient
from dip.llm.prompts import build_implement_messages
from dip.llm.structured import generate_structured
from dip.repository.index_service import IndexService
from dip.storage.repo import Store
from dip.tools.patch import PatchError, PatchService


class ImplementWorkflow:
    def __init__(
        self,
        store: Store,
        tasks: TaskService,
        compiler: ContextCompiler,
        patches: PatchService,
        index: IndexService,
        llm: LLMClient,
        verification=None,
        block_on_failed_verification: bool = True,
    ) -> None:
        self._store = store
        self._tasks = tasks
        self._compiler = compiler
        self._patches = patches
        self._index = index
        self._llm = llm
        self._verification = verification
        self._block_on_failed_verification = block_on_failed_verification

    def generate_patch(self, task_id: str) -> StoredPatchProposal:
        task = self._tasks.get_task(task_id)
        if task.state not in (TaskState.PLAN_APPROVED, TaskState.ROLLED_BACK):
            raise PatchGenerationError(
                f"Patch generation requires an approved plan; task is {task.state.value}."
            )

        plan = self._store.get_latest_plan(task_id)
        if plan is None:
            raise PatchGenerationError("No plan found for this task.")

        target_paths = [
            ref.path
            for ref in [*plan.plan.files_likely_to_change, *plan.plan.files_to_inspect]
        ]
        context = self._compiler.build_implement_context(
            task.project_id, task.request, target_paths
        )
        self._tasks.record_event(
            task_id,
            "implement_context",
            f"Compiled {len(context.source_regions)} file(s) for patch generation.",
        )

        messages = build_implement_messages(context, plan_goal=plan.plan.goal)
        result = generate_structured(self._llm, messages, PatchProposal)
        if not result.ok or result.value is None:
            self._tasks.transition(
                task_id,
                TaskState.FAILED,
                f"Patch generation failed: {result.error}",
                {"raw_response": result.raw_text[:2000]},
            )
            raise PatchGenerationError(result.error or "Unknown patch generation error")

        project_root = Path(self._project_root(task.project_id))
        preview = self._patches.preview(project_root, result.value)

        stored = StoredPatchProposal(
            id=str(uuid.uuid4()),
            task_id=task_id,
            proposal=result.value,
            preview=preview,
            context=context,
            model=result.model,
            raw_response=result.raw_text,
            repaired=result.repaired,
        )
        self._store.insert_patch_proposal(stored)

        msg = f"Patch proposed: {len(preview.file_changes)} file(s)."
        if not preview.safe:
            msg += " Not applicable as-is (see issues)."
        self._tasks.transition(task_id, TaskState.PATCH_PROPOSED, msg, {"proposal_id": stored.id})
        return stored

    def get_latest_proposal(self, task_id: str) -> StoredPatchProposal | None:
        return self._store.get_latest_patch_proposal(task_id)

    def get_latest_application(self, task_id: str) -> PatchApplication | None:
        return self._store.get_latest_application(task_id)

    def reject_patch(self, task_id: str, reason: str | None = None):
        return self._tasks.transition(
            task_id, TaskState.PLAN_APPROVED, reason or "Patch rejected by user"
        )

    def apply_patch(self, task_id: str, proposal_id: str) -> PatchApplication:
        task = self._tasks.get_task(task_id)
        if task.state != TaskState.PATCH_PROPOSED:
            raise PatchError(f"Cannot apply a patch while task is {task.state.value}.")
        stored = self._store.get_patch_proposal(proposal_id)
        if stored is None:
            raise PatchError(f"Unknown proposal: {proposal_id}")

        project_root = Path(self._project_root(task.project_id))
        application = self._patches.apply(
            project_root, task_id, proposal_id, stored.proposal
        )
        self._store.insert_patch_application(application)
        self._tasks.transition(
            task_id,
            TaskState.APPLIED,
            f"Patch applied to {len(application.changed_files)} file(s).",
            {"application_id": application.id, "files": application.changed_files},
        )
        # Keep the index consistent with the modified source.
        self._index.index_project(task.project_id)
        return application

    def rollback(self, task_id: str) -> None:
        task = self._tasks.get_task(task_id)
        if task.state != TaskState.APPLIED:
            raise PatchError(f"Nothing to roll back; task is {task.state.value}.")
        application = self._store.get_latest_application(task_id)
        if application is None:
            raise PatchError("No application to roll back.")

        project_root = Path(self._project_root(task.project_id))
        self._patches.rollback(project_root, application)
        self._store.update_application_status(application.id, "rolled_back")
        self._tasks.transition(
            task_id,
            TaskState.ROLLED_BACK,
            f"Patch rolled back ({len(application.changed_files)} file(s) restored).",
        )
        self._index.index_project(task.project_id)

    def accept(self, task_id: str, override: bool = False):
        """Mark an applied patch as accepted/done.

        Blocked when the latest verification failed unless ``override`` is set
        (the plan's "failed verification blocks automatic completion").
        """

        if self._block_on_failed_verification and not override and self._verification is not None:
            latest = self._verification.latest(task_id)
            if latest is not None and latest.status.value == "fail":
                raise CompletionBlockedError(
                    "Verification failed; resolve issues or override to accept anyway."
                )
        return self._tasks.transition(task_id, TaskState.DONE, "Change accepted by user")

    def _project_root(self, project_id: str) -> str:
        project = self._store.get_project(project_id)
        if project is None:
            raise PatchError(f"Unknown project: {project_id}")
        return project.root_path


class PatchGenerationError(RuntimeError):
    pass


class CompletionBlockedError(RuntimeError):
    pass
