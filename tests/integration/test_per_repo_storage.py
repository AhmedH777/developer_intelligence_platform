"""Per-repo container: data lives in <repo>/.dip and persists across sessions."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dip.container import Container
from dip.core.config import Settings


@pytest.fixture
def repo_copy(tmp_path: Path, sample_repo: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(sample_repo, dest)
    return dest


def _base(tmp_path: Path) -> Settings:
    # Keep the registry out of the user's home during tests.
    return Settings(registry_path=tmp_path / "registry.json")


def test_for_repo_creates_local_store_and_self_ignore(tmp_path: Path, repo_copy: Path) -> None:
    container = Container.for_repo(repo_copy, base_settings=_base(tmp_path))

    dip = repo_copy / ".dip"
    assert (dip / "platform.db").exists()
    assert (dip / ".gitignore").read_text().strip() == "*"
    assert container.project_id is not None
    assert container.project.root_path == str(repo_copy.resolve())


def test_index_persists_across_container_rebuilds(tmp_path: Path, repo_copy: Path) -> None:
    base = _base(tmp_path)
    c1 = Container.for_repo(repo_copy, base_settings=base)
    pid1 = c1.project_id
    c1.index.index_project(pid1)
    symbols_before = c1.store.count_symbols(pid1)
    assert symbols_before > 0
    c1.connection.close()

    # Re-open the same repo: same DB, same project id, data still present.
    c2 = Container.for_repo(repo_copy, base_settings=base)
    assert c2.project_id == pid1
    assert c2.store.count_symbols(pid1) == symbols_before


def test_two_repos_have_isolated_stores(tmp_path: Path, sample_repo: Path) -> None:
    base = _base(tmp_path)
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    shutil.copytree(sample_repo, repo_a)
    shutil.copytree(sample_repo, repo_b)

    ca = Container.for_repo(repo_a, base_settings=base)
    cb = Container.for_repo(repo_b, base_settings=base)
    ca.index.index_project(ca.project_id)
    # b is not indexed -> its own store is empty, proving isolation.
    assert ca.store.count_symbols(ca.project_id) > 0
    assert cb.store.count_symbols(cb.project_id) == 0
    assert (repo_a / ".dip" / "platform.db").exists()
    assert (repo_b / ".dip" / "platform.db").exists()


def test_per_repo_config_overrides_architecture_rule(tmp_path: Path, repo_copy: Path) -> None:
    # A repo-local .devintel.yaml forbids importing 'os' under the repo root.
    (repo_copy / ".devintel.yaml").write_text(
        "architecture:\n"
        "  rules:\n"
        "    - name: no-os\n"
        "      forbidden_imports: [os]\n"
        "      applies_to: ''\n"
        "      description: example repo rule\n",
        encoding="utf-8",
    )
    (repo_copy / "uses_os.py").write_text("import os\n", encoding="utf-8")

    container = Container.for_repo(repo_copy, base_settings=_base(tmp_path))
    names = [r.name for r in container.architecture.rules]
    assert names == ["no-os"]
    violations = container.architecture.check_files(str(repo_copy), ["uses_os.py"])
    assert violations and violations[0].imported_module == "os"
