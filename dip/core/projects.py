"""Project registration and lookup."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from dip.core.models import Project
from dip.storage.repo import Store


class ProjectError(ValueError):
    """Raised when a project cannot be registered (bad path, already exists)."""


class ProjectService:
    def __init__(self, store: Store) -> None:
        self._store = store

    def register_project(self, root_path: Path | str, name: str | None = None) -> Project:
        root = Path(root_path).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ProjectError(f"Path is not an existing directory: {root}")

        existing = self._store.get_project_by_path(str(root))
        if existing is not None:
            return existing

        project = Project(
            id=str(uuid.uuid4()),
            name=name or root.name,
            root_path=str(root),
            git_branch=_detect_git_branch(root),
        )
        self._store.insert_project(project)
        return project

    def get_project(self, project_id: str) -> Project:
        project = self._store.get_project(project_id)
        if project is None:
            raise ProjectError(f"Unknown project: {project_id}")
        return project

    def list_projects(self) -> list[Project]:
        return self._store.list_projects()


def _detect_git_branch(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    branch = result.stdout.strip()
    return branch or None
