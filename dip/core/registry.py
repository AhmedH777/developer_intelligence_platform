"""Cross-repo registry.

A small JSON file (independent of any repo) that records which repositories are
known to the platform, so the UI can list and switch between them. Each repo's
*data* lives in its own ``<repo>/.dip/`` store; the registry only tracks names
and paths.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RegistryEntry(BaseModel):
    name: str
    path: str
    added_at: datetime = Field(default_factory=_now)


class Registry:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path).expanduser()

    def register(self, repo_path: Path | str, name: str | None = None) -> RegistryEntry:
        root = Path(repo_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Not a directory: {root}")
        entries = self._load()
        for entry in entries:
            if entry.path == str(root):
                return entry  # idempotent by path
        entry = RegistryEntry(name=name or root.name, path=str(root))
        entries.append(entry)
        self._save(entries)
        return entry

    def list(self) -> list[RegistryEntry]:
        return self._load()

    def get(self, path: Path | str) -> RegistryEntry | None:
        target = str(Path(path).expanduser().resolve())
        return next((e for e in self._load() if e.path == target), None)

    def remove(self, path: Path | str) -> None:
        target = str(Path(path).expanduser().resolve())
        entries = [e for e in self._load() if e.path != target]
        self._save(entries)

    # ----- persistence ------------------------------------------------------
    def _load(self) -> list[RegistryEntry]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return [RegistryEntry.model_validate(item) for item in raw]

    def _save(self, entries: list[RegistryEntry]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([e.model_dump(mode="json") for e in entries], indent=2),
            encoding="utf-8",
        )
