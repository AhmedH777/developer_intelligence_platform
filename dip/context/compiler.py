"""Context compiler.

For the read-only first slice this builds the evidence package for an
"explain this symbol" request: the symbol's own source, plus its enclosing
class/module context where it fits the character budget. Every included region
records *why* it was included, and the package tracks a rough token estimate so
the UI can show exactly what was sent and how large it was.
"""

from __future__ import annotations

from dip.core.models import ContextPackage, SourceRegion, Symbol
from dip.repository.repository_service import RepositoryService

# Rough heuristic: ~4 characters per token for English + code.
CHARS_PER_TOKEN = 4


class ContextCompiler:
    def __init__(self, repository: RepositoryService, char_budget: int = 24000) -> None:
        self._repo = repository
        self._char_budget = char_budget

    def build_explain_context(self, project_id: str, symbol: Symbol) -> ContextPackage:
        notes: list[str] = []
        regions: list[SourceRegion] = []
        used_chars = 0

        # 1. The selected symbol itself — always included (highest priority).
        primary_src = self._repo.read_symbol_source(project_id, symbol)
        primary = SourceRegion(
            relative_path=symbol.relative_path,
            symbol=symbol.qualified_name,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            content=primary_src,
            kind=symbol.kind.value,
            reason="selected symbol",
        )
        regions.append(primary)
        used_chars += len(primary_src)

        # 2. Enclosing parent (class/module) for context, if it fits the budget.
        if symbol.parent_symbol_id:
            parent = self._repo.get_symbol(symbol.parent_symbol_id)
            if parent is not None and parent.kind.value != "module":
                parent_src = self._repo.read_symbol_source(project_id, parent)
                if used_chars + len(parent_src) <= self._char_budget:
                    regions.append(
                        SourceRegion(
                            relative_path=parent.relative_path,
                            symbol=parent.qualified_name,
                            start_line=parent.start_line,
                            end_line=parent.end_line,
                            content=parent_src,
                            kind=parent.kind.value,
                            reason="enclosing scope of selected symbol",
                        )
                    )
                    used_chars += len(parent_src)
                else:
                    notes.append("Enclosing scope omitted to stay within context budget.")

        char_estimate = sum(len(r.content) for r in regions)
        package = ContextPackage(
            user_request=f"Explain `{symbol.qualified_name}` in {symbol.relative_path}.",
            role="explainer",
            source_regions=regions,
            char_estimate=char_estimate,
            token_estimate=char_estimate // CHARS_PER_TOKEN,
            notes=notes,
        )
        return package
