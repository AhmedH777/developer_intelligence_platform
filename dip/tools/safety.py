"""Path safety for file edits.

Every target path is validated before any read/write: it must be relative, stay
inside the project root after normalisation, and not touch a protected path.
These checks are the enforcement points for the plan's §18 safety requirements.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


class UnsafePathError(ValueError):
    """Raised when a patch targets a path that must never be written."""


def is_protected(relative_path: str, protected_paths: list[str]) -> bool:
    """True if ``relative_path`` is, or is inside, any protected path."""

    rel = PurePosixPath(relative_path)
    parts = rel.parts
    for protected in protected_paths:
        p = protected.strip("/")
        if not p:
            continue
        # Match the protected segment anywhere in the path (e.g. ".git/...").
        prot_parts = PurePosixPath(p).parts
        if _starts_with(parts, prot_parts) or p in parts:
            return True
        if str(rel) == p:
            return True
    return False


def resolve_safe_path(
    project_root: Path, relative_path: str, protected_paths: list[str]
) -> Path:
    """Validate and resolve ``relative_path`` within ``project_root``.

    Raises :class:`UnsafePathError` for absolute paths, traversal outside the
    root, or protected paths.
    """

    if not relative_path or not relative_path.strip():
        raise UnsafePathError("Empty path.")
    if os.path.isabs(relative_path) or relative_path.startswith("~"):
        raise UnsafePathError(f"Absolute paths are not allowed: {relative_path}")
    # Normalise backslashes so Windows-style separators can't slip past checks.
    normalized = relative_path.replace("\\", "/")

    root = project_root.resolve()
    target = (root / normalized).resolve()
    if not _is_within(target, root):
        raise UnsafePathError(f"Path escapes the project root: {relative_path}")

    rel_to_root = target.relative_to(root).as_posix()
    if is_protected(rel_to_root, protected_paths):
        raise UnsafePathError(f"Path is protected: {relative_path}")
    return target


def _is_within(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _starts_with(parts: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return len(parts) >= len(prefix) and parts[: len(prefix)] == prefix
