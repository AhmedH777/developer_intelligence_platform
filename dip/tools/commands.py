"""Controlled command execution.

Commands are structured ``CommandSpec`` objects (never raw shell strings) and the
executable must be on the configured allowlist. Provides both a synchronous
``run`` (used by the verification pipeline) and an async ``start``/``poll``/
``cancel`` (used by the job runner for long-running commands with live logs).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from dip.core.config import CommandSettings
from dip.core.models import CommandResult, CommandSpec


class CommandPolicyError(ValueError):
    """Raised when a command violates the execution policy."""


class CommandRunner:
    def __init__(self, settings: CommandSettings) -> None:
        self._settings = settings

    # ----- policy -----------------------------------------------------------
    def validate(self, spec: CommandSpec) -> None:
        exe = _base_executable(spec.executable)
        if exe not in self._settings.allowed_executables:
            raise CommandPolicyError(
                f"Executable not allowed: {spec.executable!r}. "
                f"Allowed: {', '.join(self._settings.allowed_executables)}"
            )
        if not Path(spec.working_directory).is_dir():
            raise CommandPolicyError(
                f"Working directory does not exist: {spec.working_directory}"
            )

    def is_available(self, executable: str) -> bool:
        """True if the executable is allowed and resolvable on PATH."""

        exe = _base_executable(executable)
        if exe not in self._settings.allowed_executables:
            return False
        return shutil.which(executable) is not None or shutil.which(exe) is not None

    # ----- synchronous ------------------------------------------------------
    def run(self, spec: CommandSpec) -> CommandResult:
        self.validate(spec)
        start = time.monotonic()
        try:
            completed = subprocess.run(
                [spec.executable, *spec.arguments],
                cwd=spec.working_directory,
                capture_output=True,
                text=True,
                timeout=spec.timeout_seconds,
                env=_clean_env(),
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                exit_code=None,
                stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "" if isinstance(exc.stderr, str) else "")
                + f"\nTimed out after {spec.timeout_seconds}s.",
                duration_seconds=time.monotonic() - start,
                timed_out=True,
            )
        return CommandResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=time.monotonic() - start,
        )

    # ----- asynchronous (for the job runner) --------------------------------
    def start(self, spec: CommandSpec, log_path: Path) -> "RunningCommand":
        self.validate(spec)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 (closed by handle)
        process = subprocess.Popen(
            [spec.executable, *spec.arguments],
            cwd=spec.working_directory,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            env=_clean_env(),
        )
        return RunningCommand(process=process, log_file=log_file, started=time.monotonic())


@dataclass
class RunningCommand:
    process: subprocess.Popen
    log_file: object
    started: float

    def poll(self) -> int | None:
        code = self.process.poll()
        if code is not None and not self.log_file.closed:  # type: ignore[attr-defined]
            self.log_file.flush()  # type: ignore[attr-defined]
            self.log_file.close()  # type: ignore[attr-defined]
        return code

    def cancel(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if not self.log_file.closed:  # type: ignore[attr-defined]
            self.log_file.close()  # type: ignore[attr-defined]


def _base_executable(executable: str) -> str:
    """Normalise to a bare name so '/usr/bin/python3' maps to 'python3'."""

    return os.path.basename(executable)


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    # Make tool output stable and non-interactive.
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("PY_COLORS", "0")
    return env
