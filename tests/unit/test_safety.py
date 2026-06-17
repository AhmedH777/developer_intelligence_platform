from __future__ import annotations

from pathlib import Path

import pytest

from dip.tools.safety import UnsafePathError, is_protected, resolve_safe_path

PROTECTED = [".git", ".env", "secrets"]


def test_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_safe_path(tmp_path, "/etc/passwd", PROTECTED)


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_safe_path(tmp_path, "../outside.py", PROTECTED)


def test_rejects_sneaky_traversal(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_safe_path(tmp_path, "pkg/../../escape.py", PROTECTED)


def test_rejects_home_expansion(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_safe_path(tmp_path, "~/secrets.txt", PROTECTED)


def test_rejects_protected_paths(tmp_path: Path) -> None:
    for p in (".git/config", ".env", "secrets/key.pem"):
        with pytest.raises(UnsafePathError):
            resolve_safe_path(tmp_path, p, PROTECTED)


def test_allows_normal_path(tmp_path: Path) -> None:
    resolved = resolve_safe_path(tmp_path, "pkg/module.py", PROTECTED)
    assert resolved == (tmp_path / "pkg" / "module.py").resolve()


def test_is_protected_matches_nested() -> None:
    assert is_protected(".git/hooks/pre-commit", PROTECTED)
    assert is_protected("secrets/db.pem", PROTECTED)
    assert not is_protected("app/secrets_helper.py", PROTECTED)
