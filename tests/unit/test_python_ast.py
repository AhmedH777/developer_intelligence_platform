from __future__ import annotations

from dip.repository.python_ast import extract_symbols

SOURCE = '''\
"""Module docstring."""

PI = 3.14159


class Calculator:
    """A calculator."""

    def add(self, value: int) -> int:
        """Add value."""
        return value


def multiply(a: int, b: int) -> int:
    return a * b


async def fetch(url: str) -> str:
    return url
'''


def test_extracts_module_class_method_function() -> None:
    result = extract_symbols("calculator", SOURCE)
    assert result.error is None
    by_name = {s.name: s for s in result.symbols}

    assert by_name["calculator"].kind == "module"
    assert by_name["calculator"].docstring == "Module docstring."

    assert by_name["Calculator"].kind == "class"
    assert by_name["Calculator"].qualified_name == "calculator.Calculator"

    # `add` is a method because its parent is a class.
    assert by_name["add"].kind == "method"
    assert by_name["add"].qualified_name == "calculator.Calculator.add"
    assert by_name["add"].signature == "def add(self, value: int) -> int"

    # `multiply` is a top-level function.
    assert by_name["multiply"].kind == "function"
    assert by_name["multiply"].signature == "def multiply(a: int, b: int) -> int"

    # Async function signature is captured with the async prefix.
    assert by_name["fetch"].signature == "async def fetch(url: str) -> str"


def test_line_ranges_are_sensible() -> None:
    result = extract_symbols("calculator", SOURCE)
    calc = next(s for s in result.symbols if s.name == "Calculator")
    add = next(s for s in result.symbols if s.name == "add")
    # The method's range is nested within the class's range.
    assert calc.start_line <= add.start_line <= add.end_line <= calc.end_line


def test_parent_index_links_method_to_class() -> None:
    result = extract_symbols("calculator", SOURCE)
    symbols = result.symbols
    add = next(s for s in symbols if s.name == "add")
    assert add.parent_index is not None
    assert symbols[add.parent_index].name == "Calculator"


def test_syntax_error_is_reported_not_raised() -> None:
    result = extract_symbols("broken", "def oops(:\n  pass\n")
    assert result.error is not None
    assert "SyntaxError" in result.error
    assert result.symbols == []
