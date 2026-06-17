from __future__ import annotations

from pathlib import Path

from dip.core.config import DEFAULT_EXCLUDES
from dip.repository.ignore import IgnoreRules


def test_default_excludes_block_known_dirs(sample_repo: Path) -> None:
    rules = IgnoreRules.for_project(sample_repo, list(DEFAULT_EXCLUDES))
    assert rules.is_excluded_dir("__pycache__")
    assert rules.is_excluded_dir(".venv")
    assert not rules.is_excluded_dir("pkg")


def test_gitignore_directory_excluded(sample_repo: Path) -> None:
    rules = IgnoreRules.for_project(sample_repo, list(DEFAULT_EXCLUDES))
    # secret_stuff/ and build/ come from the fixture .gitignore.
    assert rules.is_excluded_dir("secret_stuff")
    assert rules.is_excluded_dir("build")


def test_gitignore_glob_file_excluded(sample_repo: Path) -> None:
    rules = IgnoreRules.for_project(sample_repo, list(DEFAULT_EXCLUDES))
    assert rules.is_excluded_file("debug.log")  # *.log
    assert not rules.is_excluded_file("calculator.py")


def test_excluded_when_any_path_component_is_excluded_dir(sample_repo: Path) -> None:
    rules = IgnoreRules.for_project(sample_repo, list(DEFAULT_EXCLUDES))
    assert rules.is_excluded_file("__pycache__/cached.py")
    assert rules.is_excluded_file("secret_stuff/hidden.py")
