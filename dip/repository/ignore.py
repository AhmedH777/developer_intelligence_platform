"""File/directory exclusion rules.

Combines a configurable list of always-excluded directory names with a small,
dependency-free interpretation of the project's ``.gitignore``. The gitignore
support is intentionally simple (it is not a full spec implementation): it
handles the common cases of directory names, simple globs, and ``*.ext``
patterns, which covers the vast majority of real exclusions.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path


class IgnoreRules:
    def __init__(self, excluded_dir_names: list[str], gitignore_patterns: list[str]) -> None:
        self._excluded_dirs = set(excluded_dir_names)
        self._patterns = gitignore_patterns

    @classmethod
    def for_project(
        cls, root: Path, excluded_dir_names: list[str]
    ) -> "IgnoreRules":
        patterns: list[str] = []
        gitignore = root / ".gitignore"
        if gitignore.exists():
            patterns = _parse_gitignore(gitignore.read_text(encoding="utf-8", errors="replace"))
        return cls(excluded_dir_names, patterns)

    def is_excluded_dir(self, dir_name: str) -> bool:
        if dir_name in self._excluded_dirs:
            return True
        return self._matches(dir_name + "/") or self._matches(dir_name)

    def is_excluded_file(self, relative_path: str) -> bool:
        parts = Path(relative_path).parts
        # Exclude if any ancestor directory is excluded (by name or pattern).
        for part in parts[:-1]:
            if self.is_excluded_dir(part):
                return True
        return self._matches(relative_path)

    def _matches(self, relative_path: str) -> bool:
        name = Path(relative_path).name
        for pattern in self._patterns:
            if fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(name, pattern):
                return True
        return False


def _parse_gitignore(text: str) -> list[str]:
    patterns: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        # Normalise a trailing slash (directory marker) and leading slash (anchor).
        line = line.rstrip("/")
        line = line.lstrip("/")
        if line:
            patterns.append(line)
    return patterns
