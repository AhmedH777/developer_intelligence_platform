"""Architecture checks over the import graph.

Rules are deterministic forbidden-import constraints (e.g. "code under dip/ must
not import streamlit"). Checks run both project-wide (for the Architecture page)
and over a patch's changed files (as a verification step that gates completion).
"""

from __future__ import annotations

from pathlib import Path

from dip.core.config import ArchitectureRule, ArchitectureSettings
from dip.core.models import ArchitectureViolation
from dip.repository.python_ast import extract_imports
from dip.storage.repo import Store


class ArchitectureService:
    def __init__(self, store: Store, settings: ArchitectureSettings) -> None:
        self._store = store
        self._rules = settings.rules

    @property
    def rules(self) -> list[ArchitectureRule]:
        return self._rules

    def check_project(self, project_id: str) -> list[ArchitectureViolation]:
        return self._check(self._store.list_imports(project_id))

    def check_files(
        self, project_root: str, relative_paths: list[str]
    ) -> list[ArchitectureViolation]:
        pairs: list[tuple[str, str]] = []
        root = Path(project_root)
        for rel in relative_paths:
            if not rel.endswith(".py"):
                continue
            try:
                content = (root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for module in extract_imports(content):
                pairs.append((rel, module))
        return self._check(pairs)

    def internal_edges(self, project_id: str) -> list[tuple[str, str]]:
        """Edges (relative_path -> imported internal module path) for the graph."""

        imports = self._store.list_imports(project_id)
        # Map indexed files to their module names so we can spot internal imports.
        module_to_path: dict[str, str] = {}
        for file in self._store.list_files(project_id):
            module_to_path[_module_name(file.relative_path)] = file.relative_path

        edges: list[tuple[str, str]] = []
        for path, module in imports:
            target = _resolve_internal(module, module_to_path)
            if target is not None and target != path:
                edges.append((path, target))
        return edges

    def _check(self, pairs: list[tuple[str, str]]) -> list[ArchitectureViolation]:
        violations: list[ArchitectureViolation] = []
        for path, module in pairs:
            for rule in self._rules:
                if rule.applies_to and not path.startswith(rule.applies_to):
                    continue
                for forbidden in rule.forbidden_imports:
                    if module == forbidden or module.startswith(forbidden + "."):
                        violations.append(
                            ArchitectureViolation(
                                rule_name=rule.name,
                                file_path=path,
                                imported_module=module,
                                description=rule.description,
                            )
                        )
        return violations


def _module_name(relative_path: str) -> str:
    p = relative_path[:-3] if relative_path.endswith(".py") else relative_path
    parts = [seg for seg in p.split("/") if seg]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else "module"


def _resolve_internal(module: str, module_to_path: dict[str, str]) -> str | None:
    if module in module_to_path:
        return module_to_path[module]
    # `from pkg.mod import X` may import a symbol; map to the module file if known.
    parent = module.rsplit(".", 1)[0]
    return module_to_path.get(parent)
