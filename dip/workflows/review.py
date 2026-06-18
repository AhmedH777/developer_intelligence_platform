"""Review workflow: structured findings on a change.

Reviews the latest patch proposal for a task: the computed diff plus the
resulting file content are given to the model, which returns findings that cite
concrete files and lines. Read-only — it never modifies anything.
"""

from __future__ import annotations

import uuid

from dip.context.compiler import ContextCompiler
from dip.core.models import ReviewResult, StoredReview
from dip.core.tasks import TaskService
from dip.llm.client import LLMClient
from dip.llm.prompts import build_review_messages
from dip.llm.structured import generate_structured
from dip.storage.repo import Store


class ReviewError(RuntimeError):
    pass


class ReviewWorkflow:
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

    def review_latest_patch(self, task_id: str) -> StoredReview:
        stored = self._store.get_latest_patch_proposal(task_id)
        if stored is None:
            raise ReviewError("No patch proposal to review for this task.")

        preview = stored.preview
        paths_and_contents = [(c.path, c.updated) for c in preview.file_changes if c.updated]
        diff = preview.combined_diff or "(no diff available)"
        context = self._compiler.build_review_context(paths_and_contents, diff)

        messages = build_review_messages(context)
        result = generate_structured(self._llm, messages, ReviewResult)
        review_result = result.value or ReviewResult(
            summary=f"Could not produce a structured review: {result.error}"
        )

        review = StoredReview(
            id=str(uuid.uuid4()),
            task_id=task_id,
            target=f"patch:{stored.id}",
            result=review_result,
            context=context,
            model=result.model,
            raw_response=result.raw_text,
            repaired=result.repaired,
        )
        self._store.insert_review(review)
        self._tasks.record_event(
            task_id,
            "review",
            f"Review produced {len(review_result.findings)} finding(s).",
        )
        return review

    def latest(self, task_id: str) -> StoredReview | None:
        return self._store.get_latest_review(task_id)
