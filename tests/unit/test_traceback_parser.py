from __future__ import annotations

from dip.tools.traceback_parser import parse_traceback

TRACEBACK = '''\
Traceback (most recent call last):
  File "/home/user/proj/app/main.py", line 12, in run
    result = compute(value)
  File "/home/user/proj/app/calc.py", line 30, in compute
    return 1 / divisor
ZeroDivisionError: division by zero
'''


def test_parses_frames_in_order() -> None:
    parsed = parse_traceback(TRACEBACK)
    assert len(parsed.frames) == 2
    first, second = parsed.frames
    assert first.file_path.endswith("app/main.py")
    assert first.line == 12
    assert first.function == "run"
    assert first.code == "result = compute(value)"
    assert second.function == "compute"
    assert second.code == "return 1 / divisor"


def test_parses_exception() -> None:
    parsed = parse_traceback(TRACEBACK)
    assert parsed.exception_type == "ZeroDivisionError"
    assert parsed.exception_message == "division by zero"


def test_exception_without_message() -> None:
    text = (
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in <module>\n'
        "    raise KeyError\n"
        "KeyError\n"
    )
    parsed = parse_traceback(text)
    assert parsed.exception_type == "KeyError"
    assert parsed.exception_message == ""


def test_dotted_exception_type() -> None:
    text = (
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in f\n'
        "    boom()\n"
        "mypkg.errors.CustomError: nope\n"
    )
    parsed = parse_traceback(text)
    assert parsed.exception_type == "mypkg.errors.CustomError"
    assert parsed.exception_message == "nope"


def test_empty_input_is_safe() -> None:
    parsed = parse_traceback("")
    assert parsed.frames == []
    assert parsed.exception_type is None
    assert not parsed.found
