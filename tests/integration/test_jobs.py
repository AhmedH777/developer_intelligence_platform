"""JobService: idempotency, async lifecycle, cancellation."""

from __future__ import annotations

import time
from pathlib import Path

from dip.container import Container
from dip.core.config import Settings
from dip.core.models import CommandSpec, JobStatus


def _project(container: Container, sample_repo: Path) -> tuple[str, str]:
    project = container.projects.register_project(sample_repo)
    return project.id, project.root_path


def _spec(root: str, args: list[str], timeout: int = 30) -> CommandSpec:
    return CommandSpec(executable="python", arguments=args, working_directory=root, timeout_seconds=timeout)


def _wait(container: Container, job_id: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = container.jobs.poll(job_id)
        if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def test_job_runs_and_captures_log(container: Container, sample_repo: Path) -> None:
    project_id, root = _project(container, sample_repo)
    job = container.jobs.enqueue_command(
        project_id, "command", _spec(root, ["-c", "print('marker-123')"]), "k1"
    )
    assert job.status == JobStatus.RUNNING
    finished = _wait(container, job.id)
    assert finished.status == JobStatus.SUCCEEDED
    assert finished.exit_code == 0
    assert "marker-123" in container.jobs.read_log(finished)


def test_failed_command_marks_job_failed(container: Container, sample_repo: Path) -> None:
    project_id, root = _project(container, sample_repo)
    job = container.jobs.enqueue_command(
        project_id, "command", _spec(root, ["-c", "import sys; sys.exit(2)"]), "k2"
    )
    finished = _wait(container, job.id)
    assert finished.status == JobStatus.FAILED
    assert finished.exit_code == 2


def test_idempotency_prevents_duplicate_active_jobs(container: Container, sample_repo: Path) -> None:
    project_id, root = _project(container, sample_repo)
    spec = _spec(root, ["-c", "import time; time.sleep(0.4)"])
    first = container.jobs.enqueue_command(project_id, "command", spec, "dup-key")
    second = container.jobs.enqueue_command(project_id, "command", spec, "dup-key")
    assert first.id == second.id  # same active job returned, not a duplicate
    _wait(container, first.id)

    # After completion the key is free again -> a new job is created.
    third = container.jobs.enqueue_command(project_id, "command", spec, "dup-key")
    assert third.id != first.id
    _wait(container, third.id)


def test_cancel_running_job(container: Container, sample_repo: Path) -> None:
    project_id, root = _project(container, sample_repo)
    job = container.jobs.enqueue_command(
        project_id, "command", _spec(root, ["-c", "import time; time.sleep(30)"]), "k-cancel"
    )
    cancelled = container.jobs.cancel(job.id)
    assert cancelled.status == JobStatus.CANCELLED
