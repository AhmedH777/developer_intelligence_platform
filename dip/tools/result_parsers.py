"""Parsers that turn raw tool output into structured diagnostics + a summary.

Each parser is pure (text in, structured out) so it is trivially testable with
canned output and never needs the tool installed.
"""

from __future__ import annotations

import json
import re

from dip.core.models import Diagnostic

# ----- pytest ---------------------------------------------------------------
_PYTEST_SUMMARY = re.compile(
    r"(?:(\d+) failed)?.*?(?:(\d+) passed)?.*?(?:(\d+) error)?", re.IGNORECASE
)
_PYTEST_FAILED_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)(?:\s+-\s+(.*))?$", re.MULTILINE)
_PYTEST_COUNTS = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped)", re.IGNORECASE)


def parse_pytest(output: str) -> tuple[list[Diagnostic], str]:
    diagnostics: list[Diagnostic] = []
    for match in _PYTEST_FAILED_LINE.finditer(output):
        nodeid, message = match.group(1), match.group(2) or ""
        file_path = nodeid.split("::", 1)[0]
        diagnostics.append(
            Diagnostic(tool="pytest", file_path=file_path, severity="error", message=message or nodeid)
        )

    counts: dict[str, int] = {}
    for match in _PYTEST_COUNTS.finditer(output):
        key = match.group(2).lower().rstrip("s")
        counts[key] = int(match.group(1))
    summary_bits = [f"{v} {k}" for k, v in counts.items()]
    summary = ", ".join(summary_bits) if summary_bits else "no tests reported"
    return diagnostics, summary


def pytest_failed(output: str, exit_code: int | None) -> bool:
    _, summary = parse_pytest(output)
    if "failed" in summary or "error" in summary:
        return True
    return exit_code not in (0, 5)  # 5 = no tests collected


# ----- ruff -----------------------------------------------------------------
def parse_ruff_json(output: str) -> tuple[list[Diagnostic], str]:
    diagnostics: list[Diagnostic] = []
    try:
        items = json.loads(output) if output.strip() else []
    except json.JSONDecodeError:
        return parse_ruff_text(output)
    for item in items:
        location = item.get("location") or {}
        diagnostics.append(
            Diagnostic(
                tool="ruff",
                file_path=item.get("filename"),
                line=location.get("row"),
                severity="warning",
                code=item.get("code"),
                message=item.get("message", ""),
            )
        )
    summary = f"{len(diagnostics)} issue(s)" if diagnostics else "clean"
    return diagnostics, summary


_RUFF_TEXT = re.compile(r"^(.*?):(\d+):\d+:\s+(\w+)\s+(.*)$", re.MULTILINE)


def parse_ruff_text(output: str) -> tuple[list[Diagnostic], str]:
    diagnostics: list[Diagnostic] = []
    for match in _RUFF_TEXT.finditer(output):
        diagnostics.append(
            Diagnostic(
                tool="ruff",
                file_path=match.group(1),
                line=int(match.group(2)),
                severity="warning",
                code=match.group(3),
                message=match.group(4),
            )
        )
    summary = f"{len(diagnostics)} issue(s)" if diagnostics else "clean"
    return diagnostics, summary


# ----- mypy -----------------------------------------------------------------
_MYPY_LINE = re.compile(
    r"^(.*?):(\d+):(?:\d+:)?\s+(error|note|warning):\s+(.*?)(?:\s+\[([\w-]+)\])?$",
    re.MULTILINE,
)


def parse_mypy(output: str) -> tuple[list[Diagnostic], str]:
    diagnostics: list[Diagnostic] = []
    for match in _MYPY_LINE.finditer(output):
        severity = match.group(3)
        if severity == "note":
            continue
        diagnostics.append(
            Diagnostic(
                tool="mypy",
                file_path=match.group(1),
                line=int(match.group(2)),
                severity=severity,
                code=match.group(5),
                message=match.group(4),
            )
        )
    errors = [d for d in diagnostics if d.severity == "error"]
    summary = f"{len(errors)} error(s)" if errors else "clean"
    return diagnostics, summary
