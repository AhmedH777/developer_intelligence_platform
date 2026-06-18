"""Unified-diff rendering for display only.

The model proposes search/replace edits, not diffs. We compute the diff
ourselves from the before/after content so the UI can show exactly what will
change. Computed diffs are always accurate — they never suffer the line-number
drift that plagues model-authored diffs.
"""

from __future__ import annotations

import difflib


def unified_diff(path: str, original: str, updated: str) -> str:
    if original == updated:
        return ""
    original_lines = original.splitlines(keepends=True)
    updated_lines = updated.splitlines(keepends=True)
    # Ensure a trailing newline so the final hunk renders cleanly.
    if original_lines and not original_lines[-1].endswith("\n"):
        original_lines[-1] += "\n"
    if updated_lines and not updated_lines[-1].endswith("\n"):
        updated_lines[-1] += "\n"
    diff = difflib.unified_diff(
        original_lines,
        updated_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)
