"""Load repository-specific skills from local markdown files.

A skill file is plain markdown: the first ``# Heading`` is the skill name, the
text before the first ``##`` is its purpose, and each ``## Section`` becomes an
entry in ``sections``. This keeps skills human-authored and version-controlled
alongside the project, with no schema ceremony.
"""

from __future__ import annotations

import re
from pathlib import Path

from dip.core.models import Skill

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "add", "use", "using",
    "a", "an", "of", "to", "in", "on", "is", "it", "be", "as", "page", "skill",
}
# Sections most useful to inject into a planning prompt.
_BRIEF_SECTIONS = ("Required steps", "Steps", "Constraints", "Verification commands")


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

    def retrieve(self, project_root: str, query: str, limit: int = 2) -> list[Skill]:
        """Return skills most relevant to ``query`` by keyword overlap."""

        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        scored: list[tuple[int, Skill]] = []
        for skill in self.load(project_root):
            haystack = " ".join([skill.name, skill.purpose, *skill.sections.values()])
            overlap = len(query_tokens & _tokens(haystack))
            if overlap:
                scored.append((overlap, skill))
        scored.sort(key=lambda t: -t[0])
        return [s for _, s in scored[:limit]]


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


def format_skill_brief(skill: Skill) -> str:
    """Compact, prompt-friendly rendering of a skill (name, purpose, key steps)."""

    parts = [f"Skill: {skill.name}"]
    if skill.purpose:
        parts.append(skill.purpose.strip())
    for heading in _BRIEF_SECTIONS:
        body = skill.sections.get(heading)
        if body:
            parts.append(f"{heading}:\n{body.strip()}")
    return "\n".join(parts)


def _tokens(text: str) -> set[str]:
    return {
        m.group(0).lower()
        for m in _TOKEN_RE.finditer(text)
        if m.group(0).lower() not in _STOPWORDS
    }
