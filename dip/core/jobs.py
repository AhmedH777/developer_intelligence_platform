"""Persistent, pollable job queue for long-running commands.

Design (the plan's §15.5, adapted to a single local process): a SQLite-backed
job table plus OS subprocesses as the workers. ``enqueue`` is idempotent — an
active job with the same key is returned instead of starting a duplicate (this is
the defence against Streamlit reruns firing the same action twice). Running
processes are tracked in-memory for the session; ``poll`` advances finished jobs
to a terminal state. Output streams to a per-job log file for live display.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from dip.core.config import Settings
from dip.core.models import CommandSpec, Job, JobStatus
from dip.storage.repo import Store
from dip.tools.commands import CommandRunner, RunningCommand


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobService:
    def __init__(self, store: Store, runner: CommandRunner, settings: Settings) -> None:
        self._store = store
        self._runner = runner
        self._settings = settings
        self._log_dir = Path(settings.storage_dir) / "logs"
        # Session-local registry of running processes, keyed by job id.
        self._running: dict[str, RunningCommand] = {}

    def enqueue_command(
        self,
        project_id: str,
        job_type: str,
        command: CommandSpec,
        idempotency_key: str,
    ) -> Job:
        # Idempotency: reuse an active job with the same key (prevents duplicates
        # from Streamlit reruns or double clicks).
        existing = self._store.find_active_job(idempotency_key)
        if existing is not None:
            return existing

        job_id = str(uuid.uuid4())
        log_path = self._log_dir / f"{job_id}.log"
        job = Job(
            id=job_id,
            project_id=project_id,
            job_type=job_type,
            idempotency_key=idempotency_key,
            status=JobStatus.RUNNING,
            command=command,
            log_path=str(log_path),
        )
        self._store.insert_job(job)
        try:
            running = self._runner.start(command, log_path)
        except Exception as exc:  # policy error or spawn failure
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(f"Failed to start command: {exc}\n", encoding="utf-8")
            self._store.update_job(job_id, JobStatus.FAILED, None, _now())
            job.status = JobStatus.FAILED
            return job
        self._running[job_id] = running
        return job

    def poll(self, job_id: str) -> Job:
        """Advance a running job to a terminal state if its process has exited."""

        job = self._store.get_job(job_id)
        if job is None:
            raise ValueError(f"Unknown job: {job_id}")
        if job.status != JobStatus.RUNNING:
            return job

        running = self._running.get(job_id)
        if running is None:
            # Process handle lost (e.g. app restarted). Mark failed so it is not
            # stuck "running" forever.
            self._store.update_job(job_id, JobStatus.FAILED, None, _now())
            job.status = JobStatus.FAILED
            return job

        code = running.poll()
        if code is None:
            return job  # still running

        status = JobStatus.SUCCEEDED if code == 0 else JobStatus.FAILED
        self._store.update_job(job_id, status, code, _now())
        self._running.pop(job_id, None)
        job.status = status
        job.exit_code = code
        return job

    def cancel(self, job_id: str) -> Job:
        job = self._store.get_job(job_id)
        if job is None:
            raise ValueError(f"Unknown job: {job_id}")
        running = self._running.get(job_id)
        if running is not None:
            running.cancel()
            self._running.pop(job_id, None)
        if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            self._store.update_job(job_id, JobStatus.CANCELLED, None, _now())
            job.status = JobStatus.CANCELLED
        return job

    def read_log(self, job: Job, max_chars: int = 20000) -> str:
        path = Path(job.log_path)
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[-max_chars:]

    def list_jobs(self, project_id: str, limit: int = 50) -> list[Job]:
        return self._store.list_jobs(project_id, limit=limit)
