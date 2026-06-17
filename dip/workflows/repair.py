"""Bounded repair workflow (the plan's §13.6).

When verification fails on an applied patch, attempt a small, capped sequence of
fixes. Every guardrail from the plan is enforced:

- hard cap on attempts (``safety.max_repair_attempts``);
- a *new* hypothesis is required each attempt (repeats stop the loop);
- stop on a repeated/oscillating failure signature;
- protected paths and the changed-file limit are enforced by the patch service;
- scope expansion (touching more files than allowed) needs explicit approval;
- tests may not be weakened without approval;
- no dependency installation (the command allowlist already forbids it).

Each attempt is applied transactionally (snapshotted) and re-verified, so a
failed attempt is fully reversible.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from dip.context.compiler import ContextCompiler
from dip.core.config import Settings
from dip.core.models import (
    PatchPreview,
    PatchProposal,
    RepairAttempt,
    RepairProposal,
    RepairResult,
    StoredPatchProposal,
    TaskState,
    VerificationStatus,
)
from dip.core.tasks import TaskService
from dip.llm.client import LLMClient
from dip.llm.prompts import build_repair_messages
from dip.llm.structured import generate_structured
from dip.repository.index_service import IndexService
from dip.storage.repo import Store
from dip.tools.patch import PatchService


class RepairWorkflow:
    def __init__(
        self,
        store: Store,
        tasks: TaskService,
        compiler: ContextCompiler,
        patches: PatchService,
        index: IndexService,
        verification,
        llm: LLMClient,
        settings: Settings,
    ) -> None:
        self._store = store
        self._tasks = tasks
        self._compiler = compiler
        self._patches = patches
        self._index = index
        self._verification = verification
        self._llm = llm
        self._settings = settings

    def run(
        self,
        task_id: str,
        allow_scope_expansion: bool = False,
        allow_test_changes: bool = False,
    ) -> RepairResult:
        task = self._tasks.get_task(task_id)
        if task.state != TaskState.APPLIED:
            return RepairResult(
                task_id=task_id,
                status="failed",
                message=f"Repair requires an applied patch; task is {task.state.value}.",
            )

        application = self._store.get_latest_application(task_id)
        if application is None or application.status != "applied":
            return RepairResult(task_id=task_id, status="failed", message="No applied patch.")

        root = Path(self._project_root(task.project_id))
        max_attempts = self._settings.safety.max_repair_attempts
        max_files = self._settings.safety.max_modified_files

        attempts: list[RepairAttempt] = []
        seen_hypotheses: set[str] = set()
        seen_signatures: set[str] = set()
        changed = list(application.changed_files)

        for n in range(1, max_attempts + 1):
            verification = self._verification.latest(task_id)
            if verification is not None and verification.status != VerificationStatus.FAIL:
                return RepairResult(
                    task_id=task_id,
                    status="fixed",
                    message="Verification already passing.",
                    attempts=attempts,
                )

            failure_text = _failure_text(verification)
            context = self._compiler.build_implement_context(task.project_id, task.request, changed)
            messages = build_repair_messages(context, failure_text, sorted(seen_hypotheses))
            result = generate_structured(self._llm, messages, RepairProposal)
            if not result.ok or result.value is None:
                attempts.append(
                    RepairAttempt(attempt=n, hypothesis="", applied=False,
                                  verification_status="n/a", note=f"model error: {result.error}")
                )
                return RepairResult(task_id=task_id, status="failed",
                                    message="Model did not return a valid repair.", attempts=attempts)

            proposal = result.value
            key = _norm(proposal.hypothesis)
            if not key or key in seen_hypotheses:
                attempts.append(
                    RepairAttempt(attempt=n, hypothesis=proposal.hypothesis, applied=False,
                                  verification_status="n/a", note="repeated/empty hypothesis")
                )
                return RepairResult(task_id=task_id, status="stopped",
                                    message="Repair repeated a hypothesis; stopping.", attempts=attempts)
            seen_hypotheses.add(key)

            patch = PatchProposal(
                summary=f"[repair] {proposal.summary or proposal.hypothesis}",
                rationale=proposal.hypothesis,
                edits=proposal.edits,
                risks=proposal.risks,
            )
            preview = self._patches.preview(root, patch)

            # Guardrails before applying.
            guard = self._guard(preview, changed, max_files, allow_scope_expansion, allow_test_changes)
            if guard is not None:
                status, note = guard
                attempts.append(
                    RepairAttempt(attempt=n, hypothesis=proposal.hypothesis, applied=False,
                                  verification_status="n/a", note=note)
                )
                return RepairResult(task_id=task_id, status=status, message=note, attempts=attempts)

            if not preview.safe:
                attempts.append(
                    RepairAttempt(attempt=n, hypothesis=proposal.hypothesis, applied=False,
                                  verification_status="n/a", note="patch not applicable (stale/unsafe)")
                )
                continue  # try a different hypothesis next round

            # Persist the repair proposal, apply it, re-verify.
            stored = StoredPatchProposal(
                id=str(uuid.uuid4()), task_id=task_id, proposal=patch, preview=preview,
                context=context, model=result.model, raw_response=result.raw_text,
                repaired=result.repaired,
            )
            self._store.insert_patch_proposal(stored)
            app = self._patches.apply(root, task_id, stored.id, patch)
            self._store.insert_patch_application(app)
            self._index.index_project(task.project_id)
            for f in app.changed_files:
                if f not in changed:
                    changed.append(f)

            run = self._verification.verify_task(task_id)
            self._tasks.record_event(
                task_id, "repair_attempt",
                f"Attempt {n}: {proposal.hypothesis} -> verification {run.status.value}",
            )
            attempts.append(
                RepairAttempt(attempt=n, hypothesis=proposal.hypothesis, applied=True,
                              verification_status=run.status.value)
            )

            if run.status != VerificationStatus.FAIL:
                return RepairResult(task_id=task_id, status="fixed",
                                    message=f"Fixed after {n} attempt(s).", attempts=attempts)

            signature = _signature(run)
            if signature in seen_signatures:
                return RepairResult(task_id=task_id, status="stopped",
                                    message="Oscillating/repeated failure; stopping.", attempts=attempts)
            seen_signatures.add(signature)

        return RepairResult(task_id=task_id, status="exhausted",
                            message=f"Still failing after {max_attempts} attempt(s).", attempts=attempts)

    # ----- guardrails -------------------------------------------------------
    def _guard(self, preview: PatchPreview, changed: list[str], max_files: int,
               allow_scope: bool, allow_tests: bool):
        touched = {c.path for c in preview.file_changes}
        new_files = touched - set(changed)
        if len(touched) > max_files and not allow_scope:
            return "needs_approval", (
                f"Repair touches {len(touched)} files (limit {max_files}); approval required."
            )
        if new_files and not allow_scope:
            return "needs_approval", (
                "Repair expands scope to new files "
                f"({', '.join(sorted(new_files))}); approval required."
            )
        if not allow_tests:
            for change in preview.file_changes:
                if _is_test_file(change.path) and _weakens_tests(change.original, change.updated):
                    return "needs_approval", (
                        f"Repair weakens tests in {change.path}; approval required."
                    )
        return None

    def _project_root(self, project_id: str) -> str:
        project = self._store.get_project(project_id)
        assert project is not None
        return project.root_path


def _failure_text(verification) -> str:
    if verification is None:
        return "(no verification details)"
    lines = []
    for step in verification.steps:
        if step.status.value == "fail":
            lines.append(f"{step.name}: {step.summary}")
            for d in step.diagnostics[:10]:
                loc = f"{d.file_path}:{d.line}" if d.file_path else ""
                lines.append(f"  - {loc} {d.message}")
    return "\n".join(lines) or "(no failing steps recorded)"


def _signature(run) -> str:
    parts = []
    for step in run.steps:
        if step.status.value == "fail":
            msgs = ";".join(sorted(d.message for d in step.diagnostics))
            parts.append(f"{step.name}:{msgs}")
    return "|".join(sorted(parts))


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    return name.startswith("test_") or "/tests/" in f"/{path}" or path.startswith("tests/")


def _weakens_tests(original: str, updated: str) -> bool:
    def count(text: str) -> tuple[int, int]:
        return text.count("def test_"), text.count("assert ")

    o_tests, o_assert = count(original)
    u_tests, u_assert = count(updated)
    return u_tests < o_tests or u_assert < o_assert
