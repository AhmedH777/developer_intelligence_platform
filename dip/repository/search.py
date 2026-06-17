"""Repository search: file path, symbol name, and keyword matching.

Implements the early steps of the plan's retrieval order (exact file match,
exact symbol match, keyword/substring search). Semantic search is deliberately
out of scope for this slice. Ranking is deterministic so it is easy to test:
exact matches rank above prefix matches, which rank above substring matches.
"""

from __future__ import annotations

from dip.core.models import SearchResult, Symbol
from dip.storage.repo import Store


def search(store: Store, project_id: str, query: str, limit: int = 50) -> list[SearchResult]:
    query = query.strip()
    if not query:
        return []

    lowered = query.lower()
    results: list[SearchResult] = []

    # File-path matches.
    for file in store.list_files(project_id):
        score, reason = _path_score(file.relative_path.lower(), lowered)
        if score > 0:
            results.append(
                SearchResult(
                    kind="file",
                    relative_path=file.relative_path,
                    score=score,
                    reason=reason,
                )
            )

    # Symbol-name matches.
    for symbol in store.search_symbols(project_id, query, limit=limit * 2):
        score, reason = _symbol_score(symbol, lowered)
        if score > 0:
            results.append(
                SearchResult(
                    kind="symbol",
                    relative_path=symbol.relative_path,
                    symbol=symbol,
                    score=score,
                    reason=reason,
                )
            )

    results.sort(key=lambda r: (-r.score, r.relative_path))
    return results[:limit]


def _path_score(path_lower: str, query_lower: str) -> tuple[float, str]:
    filename = path_lower.rsplit("/", 1)[-1]
    if filename == query_lower or filename == f"{query_lower}.py":
        return 100.0, "exact file match"
    if query_lower in path_lower:
        return 40.0, "file path contains query"
    return 0.0, ""


def _symbol_score(symbol: Symbol, query_lower: str) -> tuple[float, str]:
    name_lower = symbol.name.lower()
    if name_lower == query_lower:
        return 90.0, "exact symbol name match"
    if name_lower.startswith(query_lower):
        return 60.0, "symbol name prefix match"
    if query_lower in name_lower:
        return 30.0, "symbol name contains query"
    if query_lower in symbol.qualified_name.lower():
        return 20.0, "qualified name contains query"
    return 0.0, ""
