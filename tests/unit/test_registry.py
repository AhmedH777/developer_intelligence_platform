from __future__ import annotations

from pathlib import Path

import pytest

from dip.core.registry import Registry


def test_register_list_and_idempotent(tmp_path: Path) -> None:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    reg = Registry(tmp_path / "registry.json")

    entry = reg.register(repo)
    assert entry.name == "myrepo"
    assert entry.path == str(repo.resolve())

    # Registering the same path again returns the same entry (no duplicate).
    again = reg.register(repo)
    assert again.path == entry.path
    assert len(reg.list()) == 1


def test_register_custom_name_and_persistence(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    reg = Registry(tmp_path / "registry.json")
    reg.register(repo, name="Cool Repo")

    # A fresh Registry over the same file sees the persisted entry.
    reg2 = Registry(tmp_path / "registry.json")
    entries = reg2.list()
    assert len(entries) == 1
    assert entries[0].name == "Cool Repo"


def test_remove(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    reg = Registry(tmp_path / "registry.json")
    reg.register(repo)
    reg.remove(repo)
    assert reg.list() == []


def test_register_rejects_nonexistent_dir(tmp_path: Path) -> None:
    reg = Registry(tmp_path / "registry.json")
    with pytest.raises(ValueError):
        reg.register(tmp_path / "does-not-exist")


def test_missing_registry_file_is_empty(tmp_path: Path) -> None:
    assert Registry(tmp_path / "nope.json").list() == []
