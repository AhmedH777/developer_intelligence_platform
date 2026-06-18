"""Index orchestration: scan -> extract symbols -> persist.

Runs synchronously. For the read-only first slice this is fine; small/medium
repositories index in well under a second and there is no UI interaction during
the call. A background worker is a later-milestone concern.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from dip.core.config import Settings
from dip.core.models import IndexResult, RepositoryFile, Symbol, SymbolKind
from dip.repository.ignore import IgnoreRules
from dip.repository.python_ast import extract_imports, extract_symbols
from dip.repository.scanner import scan_python_files
from dip.storage.repo import Store


class IndexService:
    def __init__(self, store: Store, settings: Settings) -> None:
        self._store = store
        self._settings = settings

    def index_project(self, project_id: str) -> IndexResult:
        project = self._store.get_project(project_id)
        if project is None:
            raise ValueError(f"Unknown project: {project_id}")

        root = Path(project.root_path)
        ignore = IgnoreRules.for_project(root, self._settings.default_excludes)
        scanned = scan_python_files(root, ignore)

        # Full re-index: clear prior data, then repopulate. Incremental
        # (hash-based) indexing is a later optimisation.
        self._store.clear_index(project_id)

        files_indexed = 0
        symbols_indexed = 0
        skipped = 0
        errors: list[str] = []

        for sf in scanned:
            file_id = str(uuid.uuid4())
            repo_file = RepositoryFile(
                id=file_id,
                project_id=project_id,
                relative_path=sf.relative_path,
                content_hash=sf.content_hash,
                mtime=sf.mtime,
            )
            self._store.insert_file(repo_file)
            files_indexed += 1

            imports = extract_imports(sf.content)
            if imports:
                self._store.insert_imports(project_id, file_id, sf.relative_path, imports)

            module_name = _module_name(sf.relative_path)
            result = extract_symbols(module_name, sf.content)
            if result.error:
                skipped += 1
                errors.append(f"{sf.relative_path}: {result.error}")
                continue

            # Map extractor's parent_index references to generated symbol ids.
            symbol_ids: list[str] = [str(uuid.uuid4()) for _ in result.symbols]
            symbols: list[Symbol] = []
            for i, extracted in enumerate(result.symbols):
                parent_id = (
                    symbol_ids[extracted.parent_index]
                    if extracted.parent_index is not None
                    else None
                )
                symbols.append(
                    Symbol(
                        id=symbol_ids[i],
                        project_id=project_id,
                        file_id=file_id,
                        relative_path=sf.relative_path,
                        kind=SymbolKind(extracted.kind),
                        name=extracted.name,
                        qualified_name=extracted.qualified_name,
                        start_line=extracted.start_line,
                        end_line=extracted.end_line,
                        signature=extracted.signature,
                        docstring=extracted.docstring,
                        parent_symbol_id=parent_id,
                    )
                )
            self._store.insert_symbols(symbols)
            symbols_indexed += len(symbols)

        self._store.commit()
        return IndexResult(
            project_id=project_id,
            files_indexed=files_indexed,
            symbols_indexed=symbols_indexed,
            skipped_files=skipped,
            errors=errors,
        )


def _module_name(relative_path: str) -> str:
    p = relative_path[:-3] if relative_path.endswith(".py") else relative_path
    parts = [seg for seg in p.split("/") if seg]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else "module"
