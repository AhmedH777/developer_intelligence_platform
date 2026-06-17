"""Typed data-access layer over the SQLite schema.

Every method maps rows to/from the Pydantic domain models so the rest of the
codebase never touches raw rows.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from dip.core.models import (
    Project,
    RepositoryFile,
    Symbol,
    SymbolKind,
)


class Store:
    """CRUD for projects, files, and symbols."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ----- projects ---------------------------------------------------------
    def insert_project(self, project: Project) -> None:
        self._conn.execute(
            "INSERT INTO projects (id, name, root_path, git_branch, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                project.id,
                project.name,
                project.root_path,
                project.git_branch,
                project.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    def get_project(self, project_id: str) -> Project | None:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return _project_from_row(row) if row else None

    def get_project_by_path(self, root_path: str) -> Project | None:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE root_path = ?", (root_path,)
        ).fetchone()
        return _project_from_row(row) if row else None

    def list_projects(self) -> list[Project]:
        rows = self._conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
        return [_project_from_row(r) for r in rows]

    # ----- files & symbols (index lifecycle) --------------------------------
    def clear_index(self, project_id: str) -> None:
        """Remove all indexed files/symbols for a project before re-indexing."""

        self._conn.execute(
            "DELETE FROM repository_symbols WHERE project_id = ?", (project_id,)
        )
        self._conn.execute(
            "DELETE FROM repository_files WHERE project_id = ?", (project_id,)
        )
        self._conn.commit()

    def insert_file(self, file: RepositoryFile) -> None:
        self._conn.execute(
            "INSERT INTO repository_files"
            " (id, project_id, relative_path, content_hash, mtime, language, indexed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                file.id,
                file.project_id,
                file.relative_path,
                file.content_hash,
                file.mtime,
                file.language,
                file.indexed_at.isoformat(),
            ),
        )

    def insert_symbols(self, symbols: list[Symbol]) -> None:
        self._conn.executemany(
            "INSERT INTO repository_symbols"
            " (id, project_id, file_id, relative_path, kind, name, qualified_name,"
            "  start_line, end_line, signature, docstring, parent_symbol_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    s.id,
                    s.project_id,
                    s.file_id,
                    s.relative_path,
                    s.kind.value,
                    s.name,
                    s.qualified_name,
                    s.start_line,
                    s.end_line,
                    s.signature,
                    s.docstring,
                    s.parent_symbol_id,
                )
                for s in symbols
            ],
        )

    def commit(self) -> None:
        self._conn.commit()

    def list_files(self, project_id: str) -> list[RepositoryFile]:
        rows = self._conn.execute(
            "SELECT * FROM repository_files WHERE project_id = ? ORDER BY relative_path",
            (project_id,),
        ).fetchall()
        return [_file_from_row(r) for r in rows]

    def get_file_by_path(self, project_id: str, relative_path: str) -> RepositoryFile | None:
        row = self._conn.execute(
            "SELECT * FROM repository_files WHERE project_id = ? AND relative_path = ?",
            (project_id, relative_path),
        ).fetchone()
        return _file_from_row(row) if row else None

    def list_symbols_for_file(self, file_id: str) -> list[Symbol]:
        rows = self._conn.execute(
            "SELECT * FROM repository_symbols WHERE file_id = ? ORDER BY start_line",
            (file_id,),
        ).fetchall()
        return [_symbol_from_row(r) for r in rows]

    def get_symbol(self, symbol_id: str) -> Symbol | None:
        row = self._conn.execute(
            "SELECT * FROM repository_symbols WHERE id = ?", (symbol_id,)
        ).fetchone()
        return _symbol_from_row(row) if row else None

    def search_symbols(self, project_id: str, query: str, limit: int = 50) -> list[Symbol]:
        rows = self._conn.execute(
            "SELECT * FROM repository_symbols WHERE project_id = ? AND name LIKE ?"
            " ORDER BY name LIMIT ?",
            (project_id, f"%{query}%", limit),
        ).fetchall()
        return [_symbol_from_row(r) for r in rows]

    def count_symbols(self, project_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM repository_symbols WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return int(row["n"])


# ----- row mappers ----------------------------------------------------------
def _project_from_row(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        root_path=row["root_path"],
        git_branch=row["git_branch"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _file_from_row(row: sqlite3.Row) -> RepositoryFile:
    return RepositoryFile(
        id=row["id"],
        project_id=row["project_id"],
        relative_path=row["relative_path"],
        content_hash=row["content_hash"],
        mtime=row["mtime"],
        language=row["language"],
        indexed_at=datetime.fromisoformat(row["indexed_at"]),
    )


def _symbol_from_row(row: sqlite3.Row) -> Symbol:
    return Symbol(
        id=row["id"],
        project_id=row["project_id"],
        file_id=row["file_id"],
        relative_path=row["relative_path"],
        kind=SymbolKind(row["kind"]),
        name=row["name"],
        qualified_name=row["qualified_name"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        signature=row["signature"],
        docstring=row["docstring"],
        parent_symbol_id=row["parent_symbol_id"],
    )
