"""Parse a Python traceback into structured frames + the exception.

Pure and deterministic (text in, structure out). Frame classification (which
frames belong to the repository) is done by the debug workflow, which knows the
project root — the parser only extracts what the text contains.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FILE_RE = re.compile(r'^\s+File "(?P<file>.+?)", line (?P<line>\d+), in (?P<func>.+?)\s*$')


@dataclass
class RawFrame:
    file_path: str
    line: int
    function: str
    code: str = ""


@dataclass
class ParsedTraceback:
    frames: list[RawFrame] = field(default_factory=list)
    exception_type: str | None = None
    exception_message: str = ""

    @property
    def found(self) -> bool:
        return bool(self.frames) or self.exception_type is not None


def parse_traceback(text: str) -> ParsedTraceback:
    lines = text.splitlines()
    frames: list[RawFrame] = []

    for idx, line in enumerate(lines):
        match = _FILE_RE.match(line)
        if not match:
            continue
        code = ""
        # The code line (if any) is the next, more-indented, non-File line.
        if idx + 1 < len(lines):
            nxt = lines[idx + 1]
            if nxt.startswith(" ") and not _FILE_RE.match(nxt) and nxt.strip():
                code = nxt.strip()
        frames.append(
            RawFrame(
                file_path=match.group("file"),
                line=int(match.group("line")),
                function=match.group("func"),
                code=code,
            )
        )

    exc_type, exc_msg = _find_exception(lines)
    return ParsedTraceback(frames=frames, exception_type=exc_type, exception_message=exc_msg)


def _find_exception(lines: list[str]) -> tuple[str | None, str]:
    # The exception line is the last non-indented, non-"Traceback" content line.
    for line in reversed(lines):
        if not line.strip():
            continue
        if line.startswith(" ") or line.startswith("\t"):
            continue
        if line.startswith("Traceback") or line.startswith("During handling") or line.startswith(
            "The above exception"
        ):
            continue
        stripped = line.strip()
        # Looks like "ExceptionType: message" or bare "ExceptionType".
        m = re.match(r"^(?P<type>[A-Za-z_][\w.]*)\s*(?::\s*(?P<msg>.*))?$", stripped)
        if m:
            return m.group("type"), (m.group("msg") or "").strip()
        return None, stripped
    return None, ""
