"""Read-oriented repository access used by the UI and workflows."""

from __future__ import annotations

from pathlib import Path

from dip.core.models import (
    FileTreeNode,
    RepositoryFile,
    SearchResult,
    SourceFile,
    Symbol,
)
from dip.repository import search as search_module
from dip.storage.repo import Store


class RepositoryService:
    def __init__(self, store: Store) -> None:
        self._store = store

    def get_file_tree(self, project_id: str) -> FileTreeNode:
        files = self._store.list_files(project_id)
        return _build_tree(files)

    def capability_digest(
        self, project_id: str, max_files: int = 40, max_symbols_per_file: int = 8
    ) -> str:
        """A compact text summary of what the repo contains (for the Scout).

        Lists top-level packages and, per file, its classes and top-level
        functions with signatures — enough for the model to reason about the
        repo's capabilities without sending the whole codebase.
        """

        files = self._store.list_files(project_id)
        top_dirs = sorted({f.relative_path.split("/", 1)[0] for f in files if "/" in f.relative_path})
        lines: list[str] = []
        if top_dirs:
            lines.append("Top-level packages/dirs: " + ", ".join(top_dirs))
        lines.append("")
        lines.append("Modules and key symbols:")
        for file in files[:max_files]:
            symbols = self._store.list_symbols_for_file(file.id)
            notable = [
                s for s in symbols if s.kind.value in ("class", "function")
            ][:max_symbols_per_file]
            if not notable:
                continue
            parts = [s.signature or f"{s.kind.value} {s.name}" for s in notable]
            lines.append(f"- {file.relative_path}: " + "; ".join(parts))
        if len(files) > max_files:
            lines.append(f"... and {len(files) - max_files} more files")
        return "\n".join(lines)

    def get_file(self, project_id: str, relative_path: str) -> SourceFile:
        repo_file = self._store.get_file_by_path(project_id, relative_path)
        if repo_file is None:
            raise ValueError(f"File not indexed: {relative_path}")
        project = self._store.get_project(project_id)
        assert project is not None
        absolute = Path(project.root_path) / relative_path
        content = absolute.read_text(encoding="utf-8", errors="replace")
        symbols = self._store.list_symbols_for_file(repo_file.id)
        return SourceFile(file=repo_file, content=content, symbols=symbols)

    def list_symbols(self, project_id: str, relative_path: str) -> list[Symbol]:
        repo_file = self._store.get_file_by_path(project_id, relative_path)
        if repo_file is None:
            return []
        return self._store.list_symbols_for_file(repo_file.id)

    def get_symbol(self, symbol_id: str) -> Symbol | None:
        return self._store.get_symbol(symbol_id)

    def search(self, project_id: str, query: str, limit: int = 50) -> list[SearchResult]:
        return search_module.search(self._store, project_id, query, limit=limit)

    def read_symbol_source(self, project_id: str, symbol: Symbol) -> str:
        """Return the exact source text spanned by a symbol's line range."""

        project = self._store.get_project(project_id)
        assert project is not None
        absolute = Path(project.root_path) / symbol.relative_path
        lines = absolute.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(symbol.start_line - 1, 0)
        end = min(symbol.end_line, len(lines))
        return "\n".join(lines[start:end])

    def read_line_window(
        self, project_id: str, relative_path: str, center_line: int, before: int = 10, after: int = 5
    ) -> tuple[int, int, str]:
        """Return (start_line, end_line, source) around ``center_line`` (1-based)."""

        project = self._store.get_project(project_id)
        assert project is not None
        absolute = Path(project.root_path) / relative_path
        lines = absolute.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(center_line - before, 1)
        end = min(center_line + after, len(lines))
        snippet = "\n".join(lines[start - 1 : end])
        return start, end, snippet


def _build_tree(files: list[RepositoryFile]) -> FileTreeNode:
    root = FileTreeNode(name="", path="", is_dir=True)
    for file in files:
        parts = file.relative_path.split("/")
        node = root
        accumulated = ""
        for i, part in enumerate(parts):
            accumulated = f"{accumulated}/{part}" if accumulated else part
            is_dir = i < len(parts) - 1
            child = next((c for c in node.children if c.name == part), None)
            if child is None:
                child = FileTreeNode(name=part, path=accumulated, is_dir=is_dir)
                node.children.append(child)
            node = child
    _sort_tree(root)
    return root


def _sort_tree(node: FileTreeNode) -> None:
    # Directories first, then files, each alphabetically.
    node.children.sort(key=lambda c: (not c.is_dir, c.name.lower()))
    for child in node.children:
        _sort_tree(child)
