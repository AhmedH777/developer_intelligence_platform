"""Patch service: validate, preview, apply, and roll back search/replace edits.

The model never writes files. It proposes ``SearchReplaceEdit`` blocks; this
service is the only thing that touches disk, and only after:
  - every path passes safety validation (relative, in-root, not protected),
  - every search block matches its file exactly once (stale-source detection),
  - the change count is within the configured limit.

Application is transactional: a snapshot of every target file is taken first, so
a mid-apply failure (or a later user rollback) restores the exact prior state.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from dip.core.config import SafetySettings
from dip.core.models import (
    FileChange,
    PatchApplication,
    PatchPreview,
    PatchProposal,
)
from dip.tools.diffing import unified_diff
from dip.tools.safety import UnsafePathError, resolve_safe_path


class PatchError(RuntimeError):
    pass


class PatchService:
    def __init__(self, safety: SafetySettings) -> None:
        self._safety = safety

    # ----- preview / validation --------------------------------------------
    def preview(self, project_root: Path, proposal: PatchProposal) -> PatchPreview:
        """Compute per-file before/after + diffs and collect any blocking issues."""

        blocking: list[str] = []
        if not proposal.edits:
            blocking.append("Proposal contains no edits.")

        # Group edits by path so multiple edits to one file compose correctly.
        edits_by_path: dict[str, list] = {}
        for edit in proposal.edits:
            edits_by_path.setdefault(edit.path, []).append(edit)

        if len(edits_by_path) > self._safety.max_modified_files:
            blocking.append(
                f"Patch touches {len(edits_by_path)} files; limit is "
                f"{self._safety.max_modified_files}."
            )

        changes: list[FileChange] = []
        for path, edits in edits_by_path.items():
            changes.append(self._build_change(project_root, path, edits))

        return PatchPreview(file_changes=changes, blocking_issues=blocking)

    def _build_change(self, project_root: Path, path: str, edits: list) -> FileChange:
        issues: list[str] = []

        # 1. Path safety.
        try:
            target = resolve_safe_path(project_root, path, self._safety.protected_paths)
        except UnsafePathError as exc:
            return FileChange(
                path=path,
                change_type="modify",
                original="",
                updated="",
                diff="",
                applicable=False,
                issues=[str(exc)],
            )

        creating = any(e.search == "" for e in edits)
        exists = target.exists()

        if creating and len(edits) > 1:
            issues.append("File creation must be a single edit with an empty search block.")
        if creating and exists:
            issues.append("Cannot create a file that already exists.")

        if creating and not exists and not issues:
            updated = edits[0].replace
            return FileChange(
                path=path,
                change_type="create",
                original="",
                updated=updated,
                diff=unified_diff(path, "", updated),
                applicable=True,
                issues=issues,
            )

        # Modify path.
        if not exists:
            issues.append("Target file does not exist.")
            return _inapplicable(path, issues)

        original = target.read_text(encoding="utf-8", errors="replace")
        updated = original
        for edit in edits:
            if edit.search == "":
                issues.append("Empty search block on an existing file is not allowed.")
                continue
            count = updated.count(edit.search)
            if count == 0:
                issues.append(
                    "Search block not found (source may have changed): "
                    f"{_snippet(edit.search)}"
                )
            elif count > 1:
                issues.append(
                    f"Search block is ambiguous (matches {count}×): {_snippet(edit.search)}"
                )
            else:
                updated = updated.replace(edit.search, edit.replace, 1)

        applicable = not issues and updated != original
        if updated == original and not issues:
            issues.append("Edit produced no change.")
        return FileChange(
            path=path,
            change_type="modify",
            original=original,
            updated=updated,
            diff=unified_diff(path, original, updated),
            applicable=applicable,
            issues=issues,
        )

    # ----- apply / rollback -------------------------------------------------
    def apply(
        self, project_root: Path, task_id: str, proposal_id: str, proposal: PatchProposal
    ) -> PatchApplication:
        preview = self.preview(project_root, proposal)
        if not preview.safe:
            raise PatchError("Refusing to apply an unsafe or inapplicable patch.")

        snapshot: dict[str, str | None] = {}
        written: list[Path] = []
        try:
            for change in preview.file_changes:
                target = resolve_safe_path(
                    project_root, change.path, self._safety.protected_paths
                )
                snapshot[change.path] = (
                    target.read_text(encoding="utf-8", errors="replace")
                    if target.exists()
                    else None
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(change.updated, encoding="utf-8")
                written.append(target)
        except Exception as exc:  # restore anything written before failing
            self._restore(project_root, snapshot)
            raise PatchError(f"Apply failed and was rolled back: {exc}") from exc

        return PatchApplication(
            id=str(uuid.uuid4()),
            task_id=task_id,
            proposal_id=proposal_id,
            status="applied",
            changed_files=[c.path for c in preview.file_changes],
            snapshot=snapshot,
            diff=preview.combined_diff,
        )

    def rollback(self, project_root: Path, application: PatchApplication) -> None:
        if application.status != "applied":
            raise PatchError(f"Cannot roll back an application in state {application.status!r}.")
        self._restore(project_root, application.snapshot)

    def _restore(self, project_root: Path, snapshot: dict[str, str | None]) -> None:
        for path, original in snapshot.items():
            target = resolve_safe_path(project_root, path, self._safety.protected_paths)
            if original is None:
                # File was created by the patch — remove it on rollback.
                if target.exists():
                    target.unlink()
            else:
                target.write_text(original, encoding="utf-8")


def _inapplicable(path: str, issues: list[str]) -> FileChange:
    return FileChange(
        path=path,
        change_type="modify",
        original="",
        updated="",
        diff="",
        applicable=False,
        issues=issues,
    )


def _snippet(text: str, length: int = 60) -> str:
    flat = " ".join(text.split())
    return flat[:length] + ("…" if len(flat) > length else "")
