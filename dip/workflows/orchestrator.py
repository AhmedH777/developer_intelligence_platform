"""Auto-pilot orchestrator.

Chains the existing workflows — plan → patch → apply → verify → repair → accept —
so a task advances on its own, pausing only at the configured approval gates
(default: plan and patch). It performs only *non-gated* automatic actions; gated
approvals are still done explicitly (the UI calls ``plan.approve`` /
``implement.apply_patch`` and then re-invokes ``advance``).

This is the layer that makes the divided, weak-model-friendly workflows behave
like a single autonomous agent, without giving up the safety gates.
"""

from __future__ import annotations

from dip.core.config import OrchestratorSettings
from dip.core.models import (
    OrchestratorResult,
    OrchestratorStep,
    TaskState,
    VerificationStatus,
)
from dip.core.tasks import TaskService

_MAX_LEGS = 12  # safety bound against any unexpected non-advancing state


class Orchestrator:
    def __init__(
        self,
        tasks: TaskService,
        plan,
        implement,
        verification,
        repair,
        settings: OrchestratorSettings,
    ) -> None:
        self._tasks = tasks
        self._plan = plan
        self._implement = implement
        self._verification = verification
        self._repair = repair
        self._settings = settings

    def advance(self, task_id: str) -> OrchestratorResult:
        steps: list[OrchestratorStep] = []
        gates = set(self._settings.gates)

        for _ in range(_MAX_LEGS):
            task = self._tasks.get_task(task_id)
            state = task.state

            if state in (TaskState.NEW, TaskState.PLAN_REJECTED, TaskState.FAILED):
                self._plan.generate_plan(task_id)
                steps.append(OrchestratorStep(action="plan", detail="plan generated"))
                continue

            if state == TaskState.PLANNED:
                if "plan_approval" in gates:
                    return self._stop(task_id, "plan_approval", "Awaiting plan approval.", steps)
                self._plan.approve(task_id)
                steps.append(OrchestratorStep(action="approve_plan", detail="auto-approved"))
                continue

            if state == TaskState.PLAN_APPROVED:
                self._implement.generate_patch(task_id)
                steps.append(OrchestratorStep(action="patch", detail="patch proposed"))
                continue

            if state == TaskState.PATCH_PROPOSED:
                if "patch_approval" in gates:
                    return self._stop(task_id, "patch_approval", "Awaiting patch approval.", steps)
                proposal = self._implement.get_latest_proposal(task_id)
                self._implement.apply_patch(task_id, proposal.id)
                steps.append(OrchestratorStep(action="apply", detail="patch applied"))
                continue

            if state == TaskState.APPLIED:
                run = self._verification.verify_task(task_id)
                steps.append(OrchestratorStep(action="verify", detail=run.status.value))
                if run.status == VerificationStatus.FAIL and self._settings.auto_repair:
                    result = self._repair.run(task_id)
                    steps.append(OrchestratorStep(action="repair", detail=result.status))
                    run = self._verification.latest(task_id)
                if (
                    run is not None
                    and run.status != VerificationStatus.FAIL
                    and self._settings.auto_accept_on_pass
                    and "accept" not in gates
                ):
                    self._implement.accept(task_id)
                    steps.append(OrchestratorStep(action="accept", detail="accepted"))
                    continue
                return self._stop(
                    task_id, "blocked", "Verification did not pass; stopping.", steps
                )

            if state == TaskState.DONE:
                return self._stop(task_id, "done", "Task complete.", steps)
            if state in (TaskState.CANCELLED, TaskState.ROLLED_BACK):
                return self._stop(task_id, state.value, f"Task is {state.value}.", steps)

        return self._stop(task_id, "blocked", "Reached the auto-pilot step limit.", steps)

    def _stop(self, task_id: str, stopped: str, message: str, steps) -> OrchestratorResult:
        task = self._tasks.get_task(task_id)
        if steps:
            self._tasks.record_event(
                task_id,
                "orchestrator",
                f"Auto-pilot: {', '.join(s.action for s in steps)} -> {stopped}",
            )
        return OrchestratorResult(
            task_id=task_id,
            state=task.state.value,
            stopped=stopped,
            message=message,
            steps=steps,
        )
