from __future__ import annotations

from dip.tools.result_parsers import (
    parse_mypy,
    parse_pytest,
    parse_ruff_json,
    parse_ruff_text,
    pytest_failed,
)

PYTEST_FAIL = """\
F.
=================================== FAILURES ===================================
FAILED tests/test_calc.py::test_add - assert 3 == 4
============================== 1 failed, 1 passed in 0.05s ======================
"""

PYTEST_PASS = "..\n2 passed in 0.01s\n"


def test_parse_pytest_failure() -> None:
    diags, summary = parse_pytest(PYTEST_FAIL)
    assert any(d.file_path == "tests/test_calc.py" for d in diags)
    assert "1 failed" in summary
    assert pytest_failed(PYTEST_FAIL, 1)


def test_parse_pytest_pass() -> None:
    diags, summary = parse_pytest(PYTEST_PASS)
    assert diags == []
    assert "2 passed" in summary
    assert not pytest_failed(PYTEST_PASS, 0)


def test_pytest_no_tests_collected_not_failure() -> None:
    assert not pytest_failed("no tests ran", 5)


def test_parse_ruff_json() -> None:
    output = (
        '[{"filename": "a.py", "code": "F401", "message": "unused import",'
        ' "location": {"row": 3, "column": 1}}]'
    )
    diags, summary = parse_ruff_json(output)
    assert len(diags) == 1
    assert diags[0].code == "F401"
    assert diags[0].line == 3
    assert "1 issue" in summary


def test_parse_ruff_json_clean() -> None:
    diags, summary = parse_ruff_json("[]")
    assert diags == []
    assert summary == "clean"


def test_parse_ruff_text_fallback() -> None:
    diags, _ = parse_ruff_text("a.py:3:1: F401 unused import\n")
    assert diags and diags[0].code == "F401"


def test_parse_mypy() -> None:
    output = "calc.py:10: error: Incompatible return value type [return-value]\n"
    diags, summary = parse_mypy(output)
    assert len(diags) == 1
    assert diags[0].line == 10
    assert diags[0].code == "return-value"
    assert "1 error" in summary


def test_parse_mypy_clean() -> None:
    diags, summary = parse_mypy("Success: no issues found in 1 source file\n")
    assert summary == "clean"
