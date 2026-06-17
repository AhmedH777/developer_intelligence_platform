"""Python symbol extraction via the standard-library ``ast`` module.

Extracts modules, classes, functions, and methods with their line ranges,
signatures, docstrings, and parent/child nesting. Pure parsing, no I/O — given
file text it returns structured symbols. LibCST/tree-sitter are deferred; ``ast``
is sufficient and fast for read-only extraction.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass
class ExtractedSymbol:
    kind: str  # module | class | function | method
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    signature: str | None = None
    docstring: str | None = None
    # Index into the returned list of this symbol's parent, or None.
    parent_index: int | None = None


@dataclass
class ExtractionResult:
    symbols: list[ExtractedSymbol] = field(default_factory=list)
    error: str | None = None


def extract_symbols(module_name: str, source: str) -> ExtractionResult:
    """Parse ``source`` and return its symbols, or an error on a syntax failure."""

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # malformed file: report, don't crash indexing
        return ExtractionResult(error=f"SyntaxError: {exc}")

    symbols: list[ExtractedSymbol] = []

    # The module itself is symbol 0 so nested symbols can reference a parent.
    module_symbol = ExtractedSymbol(
        kind="module",
        name=module_name,
        qualified_name=module_name,
        start_line=1,
        end_line=_module_end_line(tree, source),
        docstring=ast.get_docstring(tree),
    )
    symbols.append(module_symbol)

    _walk_body(tree.body, parent_index=0, qualifier=module_name, symbols=symbols)
    return ExtractionResult(symbols=symbols)


def _walk_body(
    body: list[ast.stmt],
    parent_index: int,
    qualifier: str,
    symbols: list[ExtractedSymbol],
) -> None:
    parent_kind = symbols[parent_index].kind
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "method" if parent_kind == "class" else "function"
            symbol = ExtractedSymbol(
                kind=kind,
                name=node.name,
                qualified_name=f"{qualifier}.{node.name}",
                start_line=node.lineno,
                end_line=_node_end_line(node),
                signature=_format_signature(node),
                docstring=ast.get_docstring(node),
                parent_index=parent_index,
            )
            symbols.append(symbol)
            # Recurse so nested functions/methods are captured too.
            _walk_body(node.body, len(symbols) - 1, symbol.qualified_name, symbols)
        elif isinstance(node, ast.ClassDef):
            symbol = ExtractedSymbol(
                kind="class",
                name=node.name,
                qualified_name=f"{qualifier}.{node.name}",
                start_line=node.lineno,
                end_line=_node_end_line(node),
                signature=_format_class_signature(node),
                docstring=ast.get_docstring(node),
                parent_index=parent_index,
            )
            symbols.append(symbol)
            _walk_body(node.body, len(symbols) - 1, symbol.qualified_name, symbols)


def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = ast.unparse(node.args)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({args}){returns}"


def _format_class_signature(node: ast.ClassDef) -> str:
    bases = [ast.unparse(b) for b in node.bases]
    base_str = f"({', '.join(bases)})" if bases else ""
    return f"class {node.name}{base_str}"


def _node_end_line(node: ast.AST) -> int:
    end = getattr(node, "end_lineno", None)
    if end is not None:
        return int(end)
    return int(getattr(node, "lineno", 1))


def _module_end_line(tree: ast.Module, source: str) -> int:
    if tree.body:
        return max(_node_end_line(n) for n in tree.body)
    return len(source.splitlines()) or 1


def extract_imports(source: str) -> list[str]:
    """Return the absolute modules imported by ``source`` (relative imports skipped).

    Walks the whole tree so imports inside functions are also captured. Returns
    dotted module names, e.g. ``["os.path", "streamlit", "dip.core.tasks"]``.
    """

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.append(node.module)
    # De-duplicate while preserving order.
    seen: list[str] = []
    for m in modules:
        if m not in seen:
            seen.append(m)
    return seen
