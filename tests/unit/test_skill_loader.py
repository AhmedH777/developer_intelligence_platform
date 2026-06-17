from __future__ import annotations

from pathlib import Path

from dip.skills.loader import SkillLoader, parse_skill

SKILL_MD = """\
# Add a Streamlit Page

Use this when adding a new page to the dashboard.

## Preconditions
- A service exists for the data.

## Required steps
1. Create ui/views/foo_view.py
2. Wire it into the nav.

## Verification commands
- pytest -q
"""


def test_parse_skill_extracts_title_purpose_sections() -> None:
    skill = parse_skill(SKILL_MD, "/x/add_page.md")
    assert skill.name == "Add a Streamlit Page"
    assert "adding a new page" in skill.purpose
    assert "Preconditions" in skill.sections
    assert "A service exists" in skill.sections["Preconditions"]
    assert "Required steps" in skill.sections
    assert "Verification commands" in skill.sections


def test_loader_reads_directory(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "add_page.md").write_text(SKILL_MD, encoding="utf-8")
    (skills_dir / "other.md").write_text("# Other\n\nDoes other things.\n", encoding="utf-8")

    loader = SkillLoader()
    skills = loader.load(str(tmp_path))
    names = {s.name for s in skills}
    assert names == {"Add a Streamlit Page", "Other"}


def test_loader_missing_dir_is_empty(tmp_path: Path) -> None:
    assert SkillLoader().load(str(tmp_path)) == []
