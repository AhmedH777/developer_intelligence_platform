from __future__ import annotations

from pathlib import Path

import pytest

from dip.core.config import SafetySettings
from dip.core.models import PatchProposal, SearchReplaceEdit
from dip.tools.patch import PatchError, PatchService


def _service(max_files: int = 8) -> PatchService:
    return PatchService(SafetySettings(max_modified_files=max_files))


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_modify_preview_and_apply_and_rollback(tmp_path: Path) -> None:
    _write(tmp_path, "calc.py", "def add(a, b):\n    return a + b\n")
    svc = _service()
    proposal = PatchProposal(
        summary="rename add params",
        edits=[SearchReplaceEdit(path="calc.py", search="a + b", replace="a + b  # sum")],
    )

    preview = svc.preview(tmp_path, proposal)
    assert preview.safe
    change = preview.file_changes[0]
    assert change.change_type == "modify"
    assert "# sum" in change.updated
    assert change.diff  # a unified diff was computed

    app = svc.apply(tmp_path, "task1", "prop1", proposal)
    assert app.status == "applied"
    assert (tmp_path / "calc.py").read_text() == "def add(a, b):\n    return a + b  # sum\n"

    svc.rollback(tmp_path, app)
    assert (tmp_path / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"


def test_create_file_then_rollback_deletes_it(tmp_path: Path) -> None:
    svc = _service()
    proposal = PatchProposal(
        summary="add module",
        edits=[SearchReplaceEdit(path="pkg/new.py", search="", replace="X = 1\n")],
    )
    preview = svc.preview(tmp_path, proposal)
    assert preview.safe
    assert preview.file_changes[0].change_type == "create"

    app = svc.apply(tmp_path, "t", "p", proposal)
    assert (tmp_path / "pkg" / "new.py").exists()

    svc.rollback(tmp_path, app)
    assert not (tmp_path / "pkg" / "new.py").exists()


def test_stale_search_block_is_inapplicable(tmp_path: Path) -> None:
    _write(tmp_path, "calc.py", "def add(a, b):\n    return a + b\n")
    svc = _service()
    proposal = PatchProposal(
        summary="stale",
        edits=[SearchReplaceEdit(path="calc.py", search="return a - b", replace="x")],
    )
    preview = svc.preview(tmp_path, proposal)
    assert not preview.safe
    assert any("not found" in i for i in preview.file_changes[0].issues)
    with pytest.raises(PatchError):
        svc.apply(tmp_path, "t", "p", proposal)


def test_ambiguous_search_block_is_inapplicable(tmp_path: Path) -> None:
    _write(tmp_path, "calc.py", "x = 1\nx = 1\n")
    svc = _service()
    proposal = PatchProposal(
        summary="ambiguous",
        edits=[SearchReplaceEdit(path="calc.py", search="x = 1", replace="x = 2")],
    )
    preview = svc.preview(tmp_path, proposal)
    assert not preview.safe
    assert any("ambiguous" in i for i in preview.file_changes[0].issues)


def test_unsafe_path_blocks_apply(tmp_path: Path) -> None:
    svc = _service()
    proposal = PatchProposal(
        summary="evil",
        edits=[SearchReplaceEdit(path="../escape.py", search="", replace="bad")],
    )
    preview = svc.preview(tmp_path, proposal)
    assert not preview.safe
    assert not preview.file_changes[0].applicable


def test_too_many_files_blocks(tmp_path: Path) -> None:
    for i in range(3):
        _write(tmp_path, f"f{i}.py", "v = 0\n")
    svc = _service(max_files=2)
    proposal = PatchProposal(
        summary="big",
        edits=[
            SearchReplaceEdit(path=f"f{i}.py", search="v = 0", replace="v = 1")
            for i in range(3)
        ],
    )
    preview = svc.preview(tmp_path, proposal)
    assert not preview.safe
    assert any("limit is" in i for i in preview.blocking_issues)
