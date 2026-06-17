from __future__ import annotations

from pathlib import Path

import pytest

from dip.core.config import CommandSettings
from dip.core.models import CommandSpec
from dip.tools.commands import CommandPolicyError, CommandRunner


def _runner() -> CommandRunner:
    return CommandRunner(CommandSettings())


def test_forbidden_executable_rejected(tmp_path: Path) -> None:
    runner = _runner()
    spec = CommandSpec(executable="rm", arguments=["-rf", "/"], working_directory=str(tmp_path))
    with pytest.raises(CommandPolicyError):
        runner.validate(spec)
    with pytest.raises(CommandPolicyError):
        runner.run(spec)


def test_allowed_executable_runs(tmp_path: Path) -> None:
    runner = _runner()
    spec = CommandSpec(
        executable="python",
        arguments=["-c", "print('hello')"],
        working_directory=str(tmp_path),
    )
    result = runner.run(spec)
    assert result.ok
    assert "hello" in result.stdout


def test_nonzero_exit_is_not_ok(tmp_path: Path) -> None:
    runner = _runner()
    spec = CommandSpec(
        executable="python",
        arguments=["-c", "import sys; sys.exit(3)"],
        working_directory=str(tmp_path),
    )
    result = runner.run(spec)
    assert result.exit_code == 3
    assert not result.ok


def test_timeout_is_reported(tmp_path: Path) -> None:
    runner = _runner()
    spec = CommandSpec(
        executable="python",
        arguments=["-c", "import time; time.sleep(5)"],
        working_directory=str(tmp_path),
        timeout_seconds=1,
    )
    result = runner.run(spec)
    assert result.timed_out
    assert not result.ok


def test_base_executable_normalisation(tmp_path: Path) -> None:
    runner = _runner()
    # An absolute path whose basename is allowed should still pass policy.
    spec = CommandSpec(
        executable="/usr/local/bin/python3",
        arguments=["-c", "print(1)"],
        working_directory=str(tmp_path),
    )
    runner.validate(spec)  # should not raise


def test_missing_working_directory_rejected() -> None:
    runner = _runner()
    spec = CommandSpec(executable="python", arguments=["-c", "print(1)"], working_directory="/no/such/dir")
    with pytest.raises(CommandPolicyError):
        runner.validate(spec)
