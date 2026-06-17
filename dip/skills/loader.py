"""Load repository-specific skills from local markdown files.

A skill file is plain markdown: the first ``# Heading`` is the skill name, the
text before the first ``##`` is its purpose, and each ``## Section`` becomes an
entry in ``sections``. This keeps skills human-authored and version-controlled
alongside the project, with no schema ceremony.
"""

from __future__ import annotations

from pathlib import Path

from dip.core.models import Skill


class SkillLoader:
    def __init__(self, skills_dirname: str = "skills") -> None:
        self._dirname = skills_dirname

    def skills_dir(self, project_root: str) -> Path:
        return Path(project_root) / self._dirname

    def load(self, project_root: str) -> list[Skill]:
        directory = self.skills_dir(project_root)
        if not directory.is_dir():
            return []
        skills: list[Skill] = []
        for path in sorted(directory.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            skills.append(parse_skill(text, str(path)))
        return skills


def parse_skill(text: str, path: str) -> Skill:
    name = Path(path).stem
    purpose_lines: list[str] = []
    sections: dict[str, str] = {}

    current_section: str | None = None
    current_body: list[str] = []
    seen_title = False

    def flush() -> None:
        if current_section is not None:
            sections[current_section] = "\n".join(current_body).strip()

    for line in text.splitlines():
        if line.startswith("# ") and not seen_title:
            name = line[2:].strip() or name
            seen_title = True
            continue
        if line.startswith("## "):
            flush()
            current_section = line[3:].strip()
            current_body = []
            continue
        if current_section is None:
            purpose_lines.append(line)
        else:
            current_body.append(line)
    flush()

    purpose = "\n".join(purpose_lines).strip()
    return Skill(name=name, path=path, purpose=purpose, sections=sections, raw=text)
