"""Context compiler.

For the read-only first slice this builds the evidence package for an
"explain this symbol" request: the symbol's own source, plus its enclosing
class/module context where it fits the character budget. Every included region
records *why* it was included, and the package tracks a rough token estimate so
the UI can show exactly what was sent and how large it was.
"""

from __future__ import annotations

import re

from dip.core.models import ContextPackage, SourceRegion, Symbol
from dip.repository.repository_service import RepositoryService

# Rough heuristic: ~4 characters per token for English + code.
CHARS_PER_TOKEN = 4

# Common words that should not drive symbol search.
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "when", "then",
    "add", "fix", "make", "use", "using", "should", "would", "could", "want",
    "need", "please", "implement", "support", "change", "update", "create",
    "a", "an", "of", "to", "in", "on", "is", "it", "be", "as", "by", "or", "we",
    "function", "method", "class", "file", "code", "test", "tests",
}

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


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

    def build_plan_context(
        self, project_id: str, request: str, max_regions: int = 6
    ) -> ContextPackage:
        """Gather repository evidence relevant to a free-form feature/bug request.

        Implements the early steps of the plan's retrieval order (keyword +
        symbol-aware search). Each included region records why it was selected,
        and inclusion stops at the character budget.
        """

        notes: list[str] = []
        keywords = self._keywords(request)
        if not keywords:
            notes.append("No specific identifiers detected in the request.")

        # Best search hit per symbol across all keywords.
        best: dict[str, tuple[float, str, Symbol]] = {}
        for keyword in keywords:
            for result in self._repo.search(project_id, keyword, limit=10):
                if result.symbol is None:
                    continue
                sym = result.symbol
                prior = best.get(sym.id)
                if prior is None or result.score > prior[0]:
                    best[sym.id] = (result.score, f"matches '{keyword}' ({result.reason})", sym)

        ranked = sorted(best.values(), key=lambda t: -t[0])

        regions: list[SourceRegion] = []
        used_chars = 0
        for score, reason, sym in ranked:
            if len(regions) >= max_regions:
                break
            src = self._repo.read_symbol_source(project_id, sym)
            if used_chars + len(src) > self._char_budget:
                notes.append(f"Stopped adding evidence at the context budget ({self._char_budget} chars).")
                break
            regions.append(
                SourceRegion(
                    relative_path=sym.relative_path,
                    symbol=sym.qualified_name,
                    start_line=sym.start_line,
                    end_line=sym.end_line,
                    content=src,
                    kind=sym.kind.value,
                    reason=reason,
                )
            )
            used_chars += len(src)

        if not regions:
            notes.append("No matching symbols found; the plan will rely on the request alone.")

        char_estimate = sum(len(r.content) for r in regions)
        return ContextPackage(
            user_request=request,
            role="planner",
            source_regions=regions,
            char_estimate=char_estimate,
            token_estimate=char_estimate // CHARS_PER_TOKEN,
            notes=notes,
        )

    def build_implement_context(
        self, project_id: str, request: str, file_paths: list[str]
    ) -> ContextPackage:
        """Gather full source of the plan's target files for patch generation.

        Whole files are included (not just symbols) because the model needs exact
        surrounding text to author search/replace blocks that match verbatim.
        """

        notes: list[str] = []
        regions: list[SourceRegion] = []
        used_chars = 0
        seen: set[str] = set()
        for path in file_paths:
            if path in seen:
                continue
            seen.add(path)
            try:
                source = self._repo.get_file(project_id, path)
            except ValueError:
                notes.append(f"{path}: not in the index (may be a new file to create).")
                continue
            content = source.content
            if used_chars + len(content) > self._char_budget:
                notes.append(f"{path}: omitted to stay within the context budget.")
                continue
            line_count = content.count("\n") + 1
            regions.append(
                SourceRegion(
                    relative_path=path,
                    symbol=None,
                    start_line=1,
                    end_line=line_count,
                    content=content,
                    kind="file",
                    reason="target file from approved plan",
                )
            )
            used_chars += len(content)

        char_estimate = sum(len(r.content) for r in regions)
        return ContextPackage(
            user_request=request,
            role="coder",
            source_regions=regions,
            char_estimate=char_estimate,
            token_estimate=char_estimate // CHARS_PER_TOKEN,
            notes=notes,
        )

    @staticmethod
    def _keywords(request: str) -> list[str]:
        seen: list[str] = []
        for match in _TOKEN_RE.findall(request):
            lowered = match.lower()
            if lowered in _STOPWORDS:
                continue
            if match not in seen:
                seen.append(match)
        return seen
