"""Filesystem scanner: walk a project root and yield indexable Python files.

Deterministic and side-effect free — it only reads. Directory pruning happens
in-place so excluded trees (``.venv``, ``__pycache__``, ...) are never descended
into, which keeps scanning fast on real repositories.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from dip.repository.ignore import IgnoreRules


@dataclass(frozen=True)
class ScannedFile:
    relative_path: str
    absolute_path: Path
    content: str
    content_hash: str
    mtime: float


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scan_python_files(root: Path, ignore: IgnoreRules) -> list[ScannedFile]:
    """Return all non-ignored ``*.py`` files under ``root``."""

    root = root.resolve()
    results: list[ScannedFile] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories in place (modifying dirnames affects walk).
        dirnames[:] = [d for d in dirnames if not ignore.is_excluded_dir(d)]

        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            absolute = Path(dirpath) / filename
            relative = absolute.relative_to(root).as_posix()
            if ignore.is_excluded_file(relative):
                continue
            try:
                text = absolute.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            results.append(
                ScannedFile(
                    relative_path=relative,
                    absolute_path=absolute,
                    content=text,
                    content_hash=content_hash(text),
                    mtime=absolute.stat().st_mtime,
                )
            )

    results.sort(key=lambda f: f.relative_path)
    return results
