"""Verification pipeline.

Runs checks cheapest-first over the files a patch changed: Python syntax, then
ruff, mypy, and targeted pytest. Each step degrades gracefully — a missing tool
becomes NOT_VERIFIED rather than a failure. Results are structured, persisted,
and used to gate task completion (a blocking failure prevents marking the task
done).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from dip.core.config import Settings
from dip.core.models import (
    CommandResult,
    CommandSpec,
    Diagnostic,
    VerificationRun,
    VerificationStatus,
    VerificationStep,
)
from dip.core.tasks import TaskService
from dip.storage.repo import Store
from dip.tools.commands import CommandRunner
from dip.tools.result_parsers import (
    parse_mypy,
    parse_pytest,
    parse_ruff_json,
    pytest_failed,
)


class VerificationService:
    def __init__(
        self,
        store: Store,
        tasks: TaskService,
        runner: CommandRunner,
        settings: Settings,
        architecture=None,
    ) -> None:
        self._store = store
        self._tasks = tasks
        self._runner = runner
        self._settings = settings
        self._architecture = architecture

    def verify_task(self, task_id: str) -> VerificationRun:
        task = self._tasks.get_task(task_id)
        project = self._store.get_project(task.project_id)
        assert project is not None
        root = Path(project.root_path)

        application = self._store.get_latest_application(task_id)
        changed = (
            application.changed_files if application and application.status == "applied" else []
        )
        py_files = [f for f in changed if f.endswith(".py")]

        steps: list[VerificationStep] = []
        steps.append(self._syntax_step(root, py_files))
        steps.append(self._architecture_step(str(root), py_files))
        steps.append(self._ruff_step(root, py_files))
        steps.append(self._mypy_step(root, py_files))
        steps.append(self._pytest_step(root, py_files))

        run = VerificationRun(id=str(uuid.uuid4()), task_id=task_id, steps=steps)
        self._store.insert_verification_run(run)
        self._tasks.record_event(
            task_id,
            "verification",
            f"Verification {run.status.value}: "
            + ", ".join(f"{s.name}={s.status.value}" for s in steps),
            {"status": run.status.value},
        )
        return run

    def latest(self, task_id: str) -> VerificationRun | None:
        return self._store.get_latest_verification(task_id)

    # ----- individual steps -------------------------------------------------
    def _syntax_step(self, root: Path, py_files: list[str]) -> VerificationStep:
        if not py_files:
            return _skipped("Python syntax", "no changed Python files")
        spec = CommandSpec(
            executable="python",
            arguments=["-m", "py_compile", *py_files],
            working_directory=str(root),
            timeout_seconds=self._settings.commands.default_timeout_seconds,
        )
        result = self._runner.run(spec)
        diagnostics = (
            [Diagnostic(tool="py_compile", severity="error", message=result.stderr.strip())]
            if not result.ok
            else []
        )
        return VerificationStep(
            name="Python syntax",
            command=spec.display,
            status=VerificationStatus.PASS if result.ok else VerificationStatus.FAIL,
            duration_seconds=result.duration_seconds,
            exit_code=result.exit_code,
            blocking=True,
            diagnostics=diagnostics,
            summary="ok" if result.ok else "syntax error",
        )

    def _architecture_step(self, root: str, py_files: list[str]) -> VerificationStep:
        if self._architecture is None or not self._architecture.rules:
            return _skipped("Architecture", "no architecture rules configured")
        if not py_files:
            return _skipped("Architecture", "no changed Python files")
        violations = self._architecture.check_files(root, py_files)
        diagnostics = [
            Diagnostic(
                tool="architecture",
                file_path=v.file_path,
                severity="error",
                code=v.rule_name,
                message=f"imports '{v.imported_module}' — {v.description}",
            )
            for v in violations
        ]
        status = VerificationStatus.PASS if not violations else VerificationStatus.FAIL
        return VerificationStep(
            name="Architecture",
            command="(import-rule check)",
            status=status,
            blocking=True,
            diagnostics=diagnostics,
            summary="ok" if not violations else f"{len(violations)} violation(s)",
        )

    def _ruff_step(self, root: Path, py_files: list[str]) -> VerificationStep:
        if not self._runner.is_available("ruff"):
            return _skipped("Lint (ruff)", "ruff not available")
        if not py_files:
            return _skipped("Lint (ruff)", "no changed Python files")
        spec = CommandSpec(
            executable="ruff",
            arguments=["check", "--output-format=json", *py_files],
            working_directory=str(root),
            timeout_seconds=self._settings.commands.default_timeout_seconds,
        )
        result = self._runner.run(spec)
        diagnostics, summary = parse_ruff_json(result.stdout)
        # Lint findings are non-blocking by default (warnings, not correctness).
        status = VerificationStatus.PASS if not diagnostics else VerificationStatus.FAIL
        return VerificationStep(
            name="Lint (ruff)",
            command=spec.display,
            status=status,
            duration_seconds=result.duration_seconds,
            exit_code=result.exit_code,
            blocking=False,
            diagnostics=diagnostics,
            summary=summary,
        )

    def _mypy_step(self, root: Path, py_files: list[str]) -> VerificationStep:
        if not self._runner.is_available("mypy"):
            return _skipped("Type check (mypy)", "mypy not available")
        if not py_files:
            return _skipped("Type check (mypy)", "no changed Python files")
        spec = CommandSpec(
            executable="mypy",
            arguments=["--no-error-summary", "--hide-error-context", *py_files],
            working_directory=str(root),
            timeout_seconds=self._settings.commands.default_timeout_seconds,
        )
        result = self._runner.run(spec)
        diagnostics, summary = parse_mypy(result.stdout)
        errors = [d for d in diagnostics if d.severity == "error"]
        status = VerificationStatus.PASS if not errors else VerificationStatus.FAIL
        return VerificationStep(
            name="Type check (mypy)",
            command=spec.display,
            status=status,
            duration_seconds=result.duration_seconds,
            exit_code=result.exit_code,
            blocking=False,
            diagnostics=diagnostics,
            summary=summary,
        )

    def _pytest_step(self, root: Path, py_files: list[str]) -> VerificationStep:
        if not self._runner.is_available("pytest"):
            return _skipped("Tests (pytest)", "pytest not available")
        targets = _related_tests(root, py_files)
        if not targets:
            return VerificationStep(
                name="Tests (pytest)",
                command="pytest",
                status=VerificationStatus.MANUAL_CHECK_REQUIRED,
                blocking=False,
                summary="no related test files found; run tests manually",
            )
        spec = CommandSpec(
            executable="pytest",
            arguments=["-q", *targets],
            working_directory=str(root),
            timeout_seconds=self._settings.commands.default_timeout_seconds,
        )
        result = self._runner.run(spec)
        diagnostics, summary = parse_pytest(result.stdout + "\n" + result.stderr)
        failed = pytest_failed(result.stdout + "\n" + result.stderr, result.exit_code)
        return VerificationStep(
            name="Tests (pytest)",
            command=spec.display,
            status=VerificationStatus.FAIL if failed else VerificationStatus.PASS,
            duration_seconds=result.duration_seconds,
            exit_code=result.exit_code,
            blocking=True,
            diagnostics=diagnostics,
            summary=summary,
        )


def _skipped(name: str, reason: str) -> VerificationStep:
    return VerificationStep(
        name=name,
        command="(skipped)",
        status=VerificationStatus.NOT_VERIFIED,
        blocking=False,
        summary=reason,
    )


def _related_tests(root: Path, py_files: list[str]) -> list[str]:
    """Find test files related to the changed files by naming convention."""

    targets: list[str] = []
    for rel in py_files:
        name = Path(rel).stem
        if name.startswith("test_"):
            if (root / rel).exists():
                targets.append(rel)
            continue
        for candidate in (f"test_{name}.py", f"tests/test_{name}.py"):
            if (root / candidate).exists() and candidate not in targets:
                targets.append(candidate)
    return targets
