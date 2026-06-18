from __future__ import annotations

from pathlib import Path

from dip.core.config import ArchitectureRule, ArchitectureSettings
from dip.repository.python_ast import extract_imports


def test_extract_imports_absolute_only() -> None:
    src = (
        "import os\n"
        "import os.path\n"
        "from collections import OrderedDict\n"
        "from . import sibling\n"  # relative -> skipped
        "from .pkg import thing\n"  # relative -> skipped
        "import streamlit as st\n"
    )
    mods = extract_imports(src)
    assert "os" in mods
    assert "os.path" in mods
    assert "collections" in mods
    assert "streamlit" in mods
    assert "sibling" not in mods
    assert "pkg" not in mods


def test_extract_imports_inside_function() -> None:
    src = "def f():\n    import streamlit\n    return streamlit\n"
    assert "streamlit" in extract_imports(src)


def test_extract_imports_handles_syntax_error() -> None:
    assert extract_imports("def broken(:\n") == []


def _settings() -> ArchitectureSettings:
    return ArchitectureSettings(
        rules=[
            ArchitectureRule(
                name="ui-agnostic-backend",
                forbidden_imports=["streamlit"],
                applies_to="dip/",
                description="no streamlit in dip/",
            )
        ]
    )


def test_check_files_flags_forbidden_import(tmp_path: Path, sample_repo) -> None:
    # Use a store-less check via the service over the filesystem.
    from dip.repository.architecture import ArchitectureService

    (tmp_path / "dip").mkdir()
    (tmp_path / "dip" / "bad.py").write_text("import streamlit\n", encoding="utf-8")
    (tmp_path / "dip" / "good.py").write_text("import os\n", encoding="utf-8")
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "page.py").write_text("import streamlit\n", encoding="utf-8")  # allowed in ui/

    svc = ArchitectureService(store=None, settings=_settings())  # type: ignore[arg-type]
    violations = svc.check_files(str(tmp_path), ["dip/bad.py", "dip/good.py", "ui/page.py"])
    assert len(violations) == 1
    v = violations[0]
    assert v.file_path == "dip/bad.py"
    assert v.imported_module == "streamlit"
    assert v.rule_name == "ui-agnostic-backend"
