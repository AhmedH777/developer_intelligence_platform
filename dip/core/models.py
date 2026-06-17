"""Pydantic domain models shared across services and the UI.

These are the typed contracts the plan calls for. Persistence (``dip.storage``)
maps them to/from SQLite rows; the UI renders them directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SymbolKind(str, Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"


class Project(BaseModel):
    id: str
    name: str
    root_path: str
    git_branch: str | None = None
    created_at: datetime = Field(default_factory=_now)


class RepositoryFile(BaseModel):
    id: str
    project_id: str
    relative_path: str
    content_hash: str
    mtime: float
    language: str = "python"
    indexed_at: datetime = Field(default_factory=_now)


class Symbol(BaseModel):
    id: str
    project_id: str
    file_id: str
    relative_path: str
    kind: SymbolKind
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    signature: str | None = None
    docstring: str | None = None
    parent_symbol_id: str | None = None


class SourceFile(BaseModel):
    """A file's content plus the symbols defined in it."""

    file: RepositoryFile
    content: str
    symbols: list[Symbol] = Field(default_factory=list)


class FileTreeNode(BaseModel):
    """A node in the project file tree (directory or file)."""

    name: str
    path: str
    is_dir: bool
    children: list["FileTreeNode"] = Field(default_factory=list)


class SearchResult(BaseModel):
    kind: str  # "file" | "symbol"
    relative_path: str
    symbol: Symbol | None = None
    score: float
    reason: str


class SourceRegion(BaseModel):
    """A contiguous slice of source included in a context package."""

    relative_path: str
    symbol: str | None
    start_line: int
    end_line: int
    content: str
    kind: str
    language: str = "python"
    reason: str = ""


class ContextPackage(BaseModel):
    """Everything sent to the model for one request, with inclusion reasons.

    Kept deliberately transparent so the UI can show exactly what the model saw
    (the plan's evidence-visibility requirement).
    """

    user_request: str
    role: str = "explainer"
    source_regions: list[SourceRegion] = Field(default_factory=list)
    char_estimate: int = 0
    token_estimate: int = 0
    notes: list[str] = Field(default_factory=list)


class IndexResult(BaseModel):
    project_id: str
    files_indexed: int
    symbols_indexed: int
    skipped_files: int = 0
    errors: list[str] = Field(default_factory=list)


class Explanation(BaseModel):
    """The model's answer for an explain request, paired with its evidence."""

    project_id: str
    symbol_id: str
    text: str
    context: ContextPackage
    model: str
    raw_response: dict[str, Any] = Field(default_factory=dict)


FileTreeNode.model_rebuild()
