"""Task lifecycle: persistent tasks, a guarded state machine, and an event log.

Every state change is validated against ``TASK_TRANSITIONS`` and recorded as a
``TaskEvent``, giving each task a complete, inspectable history (the plan's
audit-trail requirement).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from dip.core.models import (
    TASK_TRANSITIONS,
    Task,
    TaskEvent,
    TaskState,
)
from dip.storage.repo import Store


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskError(ValueError):
    """Raised for unknown tasks or illegal state transitions."""


class TaskService:
    def __init__(self, store: Store) -> None:
        self._store = store

    def create_task(self, project_id: str, title: str, request: str) -> Task:
        title = title.strip() or request.strip()[:60] or "Untitled task"
        task = Task(
            id=str(uuid.uuid4()),
            project_id=project_id,
            title=title,
            request=request.strip(),
            state=TaskState.NEW,
        )
        self._store.insert_task(task)
        self._record(task.id, "created", f"Task created: {title}")
        return task

    def get_task(self, task_id: str) -> Task:
        task = self._store.get_task(task_id)
        if task is None:
            raise TaskError(f"Unknown task: {task_id}")
        return task

    def list_tasks(self, project_id: str) -> list[Task]:
        return self._store.list_tasks(project_id)

    def list_events(self, task_id: str) -> list[TaskEvent]:
        return self._store.list_events(task_id)

    def transition(
        self,
        task_id: str,
        new_state: TaskState,
        message: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Task:
        task = self.get_task(task_id)
        allowed = TASK_TRANSITIONS.get(task.state, set())
        if new_state not in allowed:
            raise TaskError(
                f"Illegal transition {task.state.value} -> {new_state.value} "
                f"for task {task_id}."
            )
        now = _now()
        self._store.update_task_state(task_id, new_state, now)
        self._record(
            task_id,
            "state_change",
            message or f"{task.state.value} -> {new_state.value}",
            {"from": task.state.value, "to": new_state.value, **(data or {})},
        )
        task.state = new_state
        task.updated_at = now
        return task

    def record_event(
        self, task_id: str, event_type: str, message: str, data: dict[str, Any] | None = None
    ) -> None:
        self._record(task_id, event_type, message, data)

    def _record(
        self, task_id: str, event_type: str, message: str, data: dict[str, Any] | None = None
    ) -> None:
        event = TaskEvent(
            id=str(uuid.uuid4()),
            task_id=task_id,
            event_type=event_type,
            message=message,
            data=data or {},
        )
        self._store.insert_event(event)
