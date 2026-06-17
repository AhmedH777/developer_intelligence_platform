"""Typed data-access layer over the SQLite schema.

Every method maps rows to/from the Pydantic domain models so the rest of the
codebase never touches raw rows.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from dip.core.models import (
    CommandSpec,
    ContextPackage,
    ImplementationPlan,
    Job,
    JobStatus,
    PatchApplication,
    PatchPreview,
    PatchProposal,
    PlanGrounding,
    Project,
    RepositoryFile,
    StoredDebugReport,
    StoredPatchProposal,
    StoredPlan,
    StoredReview,
    Symbol,
    SymbolKind,
    Task,
    TaskEvent,
    TaskState,
    VerificationRun,
    VerificationStatus,
    VerificationStep,
)


class Store:
    """CRUD for projects, files, and symbols."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ----- projects ---------------------------------------------------------
    def insert_project(self, project: Project) -> None:
        self._conn.execute(
            "INSERT INTO projects (id, name, root_path, git_branch, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                project.id,
                project.name,
                project.root_path,
                project.git_branch,
                project.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    def get_project(self, project_id: str) -> Project | None:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return _project_from_row(row) if row else None

    def get_project_by_path(self, root_path: str) -> Project | None:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE root_path = ?", (root_path,)
        ).fetchone()
        return _project_from_row(row) if row else None

    def list_projects(self) -> list[Project]:
        rows = self._conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
        return [_project_from_row(r) for r in rows]

    # ----- files & symbols (index lifecycle) --------------------------------
    def clear_index(self, project_id: str) -> None:
        """Remove all indexed files/symbols for a project before re-indexing."""

        self._conn.execute(
            "DELETE FROM repository_symbols WHERE project_id = ?", (project_id,)
        )
        self._conn.execute(
            "DELETE FROM repository_files WHERE project_id = ?", (project_id,)
        )
        self._conn.commit()

    def insert_file(self, file: RepositoryFile) -> None:
        self._conn.execute(
            "INSERT INTO repository_files"
            " (id, project_id, relative_path, content_hash, mtime, language, indexed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                file.id,
                file.project_id,
                file.relative_path,
                file.content_hash,
                file.mtime,
                file.language,
                file.indexed_at.isoformat(),
            ),
        )

    def insert_symbols(self, symbols: list[Symbol]) -> None:
        self._conn.executemany(
            "INSERT INTO repository_symbols"
            " (id, project_id, file_id, relative_path, kind, name, qualified_name,"
            "  start_line, end_line, signature, docstring, parent_symbol_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    s.id,
                    s.project_id,
                    s.file_id,
                    s.relative_path,
                    s.kind.value,
                    s.name,
                    s.qualified_name,
                    s.start_line,
                    s.end_line,
                    s.signature,
                    s.docstring,
                    s.parent_symbol_id,
                )
                for s in symbols
            ],
        )

    def commit(self) -> None:
        self._conn.commit()

    def list_files(self, project_id: str) -> list[RepositoryFile]:
        rows = self._conn.execute(
            "SELECT * FROM repository_files WHERE project_id = ? ORDER BY relative_path",
            (project_id,),
        ).fetchall()
        return [_file_from_row(r) for r in rows]

    def get_file_by_path(self, project_id: str, relative_path: str) -> RepositoryFile | None:
        row = self._conn.execute(
            "SELECT * FROM repository_files WHERE project_id = ? AND relative_path = ?",
            (project_id, relative_path),
        ).fetchone()
        return _file_from_row(row) if row else None

    def list_symbols_for_file(self, file_id: str) -> list[Symbol]:
        rows = self._conn.execute(
            "SELECT * FROM repository_symbols WHERE file_id = ? ORDER BY start_line",
            (file_id,),
        ).fetchall()
        return [_symbol_from_row(r) for r in rows]

    def get_symbol(self, symbol_id: str) -> Symbol | None:
        row = self._conn.execute(
            "SELECT * FROM repository_symbols WHERE id = ?", (symbol_id,)
        ).fetchone()
        return _symbol_from_row(row) if row else None

    def search_symbols(self, project_id: str, query: str, limit: int = 50) -> list[Symbol]:
        rows = self._conn.execute(
            "SELECT * FROM repository_symbols WHERE project_id = ? AND name LIKE ?"
            " ORDER BY name LIMIT ?",
            (project_id, f"%{query}%", limit),
        ).fetchall()
        return [_symbol_from_row(r) for r in rows]

    def count_symbols(self, project_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM repository_symbols WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return int(row["n"])

    # ----- tasks ------------------------------------------------------------
    def insert_task(self, task: Task) -> None:
        self._conn.execute(
            "INSERT INTO tasks (id, project_id, title, request, state, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                task.id,
                task.project_id,
                task.title,
                task.request,
                task.state.value,
                task.created_at.isoformat(),
                task.updated_at.isoformat(),
            ),
        )
        self._conn.commit()

    def update_task_state(self, task_id: str, state: TaskState, updated_at: datetime) -> None:
        self._conn.execute(
            "UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?",
            (state.value, updated_at.isoformat(), task_id),
        )
        self._conn.commit()

    def get_task(self, task_id: str) -> Task | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_from_row(row) if row else None

    def list_tasks(self, project_id: str) -> list[Task]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        return [_task_from_row(r) for r in rows]

    # ----- task events ------------------------------------------------------
    def insert_event(self, event: TaskEvent) -> None:
        self._conn.execute(
            "INSERT INTO task_events (id, task_id, created_at, event_type, message, data)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.task_id,
                event.created_at.isoformat(),
                event.event_type,
                event.message,
                json.dumps(event.data),
            ),
        )
        self._conn.commit()

    def list_events(self, task_id: str) -> list[TaskEvent]:
        rows = self._conn.execute(
            "SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        return [_event_from_row(r) for r in rows]

    # ----- plans ------------------------------------------------------------
    def insert_plan(self, plan: StoredPlan) -> None:
        self._conn.execute(
            "INSERT INTO plans"
            " (id, task_id, created_at, model, repaired, plan_json, grounding_json,"
            "  context_json, raw_response)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                plan.id,
                plan.task_id,
                plan.created_at.isoformat(),
                plan.model,
                1 if plan.repaired else 0,
                plan.plan.model_dump_json(),
                plan.grounding.model_dump_json(),
                plan.context.model_dump_json(),
                plan.raw_response,
            ),
        )
        self._conn.commit()

    def get_latest_plan(self, task_id: str) -> StoredPlan | None:
        row = self._conn.execute(
            "SELECT * FROM plans WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return _plan_from_row(row) if row else None

    # ----- patch proposals --------------------------------------------------
    def insert_patch_proposal(self, proposal: StoredPatchProposal) -> None:
        self._conn.execute(
            "INSERT INTO patch_proposals"
            " (id, task_id, created_at, model, repaired, proposal_json, preview_json,"
            "  context_json, raw_response)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                proposal.id,
                proposal.task_id,
                proposal.created_at.isoformat(),
                proposal.model,
                1 if proposal.repaired else 0,
                proposal.proposal.model_dump_json(),
                proposal.preview.model_dump_json(),
                proposal.context.model_dump_json(),
                proposal.raw_response,
            ),
        )
        self._conn.commit()

    def get_patch_proposal(self, proposal_id: str) -> StoredPatchProposal | None:
        row = self._conn.execute(
            "SELECT * FROM patch_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        return _proposal_from_row(row) if row else None

    def get_latest_patch_proposal(self, task_id: str) -> StoredPatchProposal | None:
        row = self._conn.execute(
            "SELECT * FROM patch_proposals WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return _proposal_from_row(row) if row else None

    # ----- patch applications -----------------------------------------------
    def insert_patch_application(self, application: PatchApplication) -> None:
        self._conn.execute(
            "INSERT INTO patch_applications"
            " (id, task_id, proposal_id, created_at, status, changed_files, snapshot_json, diff)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                application.id,
                application.task_id,
                application.proposal_id,
                application.created_at.isoformat(),
                application.status,
                json.dumps(application.changed_files),
                json.dumps(application.snapshot),
                application.diff,
            ),
        )
        self._conn.commit()

    def update_application_status(self, application_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE patch_applications SET status = ? WHERE id = ?",
            (status, application_id),
        )
        self._conn.commit()

    def get_latest_application(self, task_id: str) -> PatchApplication | None:
        row = self._conn.execute(
            "SELECT * FROM patch_applications WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return _application_from_row(row) if row else None

    # ----- jobs -------------------------------------------------------------
    def insert_job(self, job: Job) -> None:
        self._conn.execute(
            "INSERT INTO jobs"
            " (id, project_id, job_type, idempotency_key, status, command_json,"
            "  log_path, exit_code, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job.id,
                job.project_id,
                job.job_type,
                job.idempotency_key,
                job.status.value,
                job.command.model_dump_json(),
                job.log_path,
                job.exit_code,
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
            ),
        )
        self._conn.commit()

    def update_job(self, job_id: str, status: JobStatus, exit_code: int | None, updated_at: datetime) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = ?, exit_code = ?, updated_at = ? WHERE id = ?",
            (status.value, exit_code, updated_at.isoformat(), job_id),
        )
        self._conn.commit()

    def get_job(self, job_id: str) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _job_from_row(row) if row else None

    def find_active_job(self, idempotency_key: str) -> Job | None:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE idempotency_key = ? AND status IN ('queued','running')"
            " ORDER BY created_at DESC LIMIT 1",
            (idempotency_key,),
        ).fetchone()
        return _job_from_row(row) if row else None

    def list_jobs(self, project_id: str, limit: int = 50) -> list[Job]:
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
        return [_job_from_row(r) for r in rows]

    # ----- verification runs ------------------------------------------------
    def insert_verification_run(self, run: VerificationRun) -> None:
        self._conn.execute(
            "INSERT INTO verification_runs (id, task_id, created_at, status, steps_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                run.id,
                run.task_id,
                run.created_at.isoformat(),
                run.status.value,
                json.dumps([s.model_dump() for s in run.steps]),
            ),
        )
        self._conn.commit()

    def get_latest_verification(self, task_id: str) -> VerificationRun | None:
        row = self._conn.execute(
            "SELECT * FROM verification_runs WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return _verification_from_row(row) if row else None

    # ----- debug reports ----------------------------------------------------
    def insert_debug_report(self, report: StoredDebugReport) -> None:
        self._conn.execute(
            "INSERT INTO debug_reports (id, task_id, created_at, payload_json)"
            " VALUES (?, ?, ?, ?)",
            (report.id, report.task_id, report.created_at.isoformat(), report.model_dump_json()),
        )
        self._conn.commit()

    def get_latest_debug_report(self, task_id: str) -> StoredDebugReport | None:
        row = self._conn.execute(
            "SELECT payload_json FROM debug_reports WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return StoredDebugReport.model_validate_json(row["payload_json"]) if row else None

    # ----- review runs ------------------------------------------------------
    def insert_review(self, review: StoredReview) -> None:
        self._conn.execute(
            "INSERT INTO review_runs (id, task_id, created_at, payload_json)"
            " VALUES (?, ?, ?, ?)",
            (review.id, review.task_id, review.created_at.isoformat(), review.model_dump_json()),
        )
        self._conn.commit()

    def get_latest_review(self, task_id: str) -> StoredReview | None:
        row = self._conn.execute(
            "SELECT payload_json FROM review_runs WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return StoredReview.model_validate_json(row["payload_json"]) if row else None


# ----- row mappers ----------------------------------------------------------
def _project_from_row(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        root_path=row["root_path"],
        git_branch=row["git_branch"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _file_from_row(row: sqlite3.Row) -> RepositoryFile:
    return RepositoryFile(
        id=row["id"],
        project_id=row["project_id"],
        relative_path=row["relative_path"],
        content_hash=row["content_hash"],
        mtime=row["mtime"],
        language=row["language"],
        indexed_at=datetime.fromisoformat(row["indexed_at"]),
    )


def _symbol_from_row(row: sqlite3.Row) -> Symbol:
    return Symbol(
        id=row["id"],
        project_id=row["project_id"],
        file_id=row["file_id"],
        relative_path=row["relative_path"],
        kind=SymbolKind(row["kind"]),
        name=row["name"],
        qualified_name=row["qualified_name"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        signature=row["signature"],
        docstring=row["docstring"],
        parent_symbol_id=row["parent_symbol_id"],
    )


def _task_from_row(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        request=row["request"],
        state=TaskState(row["state"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _event_from_row(row: sqlite3.Row) -> TaskEvent:
    return TaskEvent(
        id=row["id"],
        task_id=row["task_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        event_type=row["event_type"],
        message=row["message"],
        data=json.loads(row["data"]),
    )


def _plan_from_row(row: sqlite3.Row) -> StoredPlan:
    return StoredPlan(
        id=row["id"],
        task_id=row["task_id"],
        plan=ImplementationPlan.model_validate_json(row["plan_json"]),
        grounding=PlanGrounding.model_validate_json(row["grounding_json"]),
        context=ContextPackage.model_validate_json(row["context_json"]),
        model=row["model"],
        created_at=datetime.fromisoformat(row["created_at"]),
        raw_response=row["raw_response"],
        repaired=bool(row["repaired"]),
    )


def _proposal_from_row(row: sqlite3.Row) -> StoredPatchProposal:
    return StoredPatchProposal(
        id=row["id"],
        task_id=row["task_id"],
        proposal=PatchProposal.model_validate_json(row["proposal_json"]),
        preview=PatchPreview.model_validate_json(row["preview_json"]),
        context=ContextPackage.model_validate_json(row["context_json"]),
        model=row["model"],
        created_at=datetime.fromisoformat(row["created_at"]),
        raw_response=row["raw_response"],
        repaired=bool(row["repaired"]),
    )


def _application_from_row(row: sqlite3.Row) -> PatchApplication:
    return PatchApplication(
        id=row["id"],
        task_id=row["task_id"],
        proposal_id=row["proposal_id"],
        status=row["status"],
        changed_files=json.loads(row["changed_files"]),
        snapshot=json.loads(row["snapshot_json"]),
        diff=row["diff"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _job_from_row(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        project_id=row["project_id"],
        job_type=row["job_type"],
        idempotency_key=row["idempotency_key"],
        status=JobStatus(row["status"]),
        command=CommandSpec.model_validate_json(row["command_json"]),
        log_path=row["log_path"],
        exit_code=row["exit_code"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _verification_from_row(row: sqlite3.Row) -> VerificationRun:
    steps = [VerificationStep.model_validate(s) for s in json.loads(row["steps_json"])]
    return VerificationRun(
        id=row["id"],
        task_id=row["task_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        steps=steps,
    )
