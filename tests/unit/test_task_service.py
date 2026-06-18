from __future__ import annotations

from pathlib import Path

import pytest

from dip.container import Container
from dip.core.models import TaskState
from dip.core.tasks import TaskError


def _project(container: Container, sample_repo: Path) -> str:
    return container.projects.register_project(sample_repo).id


def test_create_task_starts_new_with_created_event(container: Container, sample_repo: Path) -> None:
    project_id = _project(container, sample_repo)
    task = container.tasks.create_task(project_id, "Add reset", "Add a reset method")
    assert task.state == TaskState.NEW
    events = container.tasks.list_events(task.id)
    assert [e.event_type for e in events] == ["created"]


def test_legal_transition_records_event(container: Container, sample_repo: Path) -> None:
    project_id = _project(container, sample_repo)
    task = container.tasks.create_task(project_id, "t", "do something")
    updated = container.tasks.transition(task.id, TaskState.INVESTIGATING)
    assert updated.state == TaskState.INVESTIGATING
    # Reload from storage to confirm persistence.
    assert container.tasks.get_task(task.id).state == TaskState.INVESTIGATING
    types = [e.event_type for e in container.tasks.list_events(task.id)]
    assert "state_change" in types


def test_illegal_transition_rejected(container: Container, sample_repo: Path) -> None:
    project_id = _project(container, sample_repo)
    task = container.tasks.create_task(project_id, "t", "do something")
    # NEW -> PLAN_APPROVED is not allowed.
    with pytest.raises(TaskError):
        container.tasks.transition(task.id, TaskState.PLAN_APPROVED)


def test_title_defaults_to_request_snippet(container: Container, sample_repo: Path) -> None:
    project_id = _project(container, sample_repo)
    task = container.tasks.create_task(project_id, "   ", "Make the calculator subtract")
    assert task.title.startswith("Make the calculator")
