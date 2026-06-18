"""Project memory: durable, source-attributed knowledge.

Memory is created deliberately (never by silently storing conversation), is fully
manageable (edit / enable / disable / delete), and can be retrieved by relevance
to be injected into later context packages.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from dip.core.models import MemoryCategory, MemoryItem
from dip.storage.repo import Store

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "use", "using",
    "add", "the", "a", "an", "of", "to", "in", "on", "is", "it", "be", "as",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryService:
    def __init__(self, store: Store) -> None:
        self._store = store

    def add(
        self,
        project_id: str,
        category: MemoryCategory,
        content: str,
        source_task_id: str | None = None,
        confidence: float = 0.8,
    ) -> MemoryItem:
        item = MemoryItem(
            id=str(uuid.uuid4()),
            project_id=project_id,
            category=category,
            content=content.strip(),
            source_task_id=source_task_id,
            confidence=confidence,
        )
        self._store.insert_memory(item)
        return item

    def list(self, project_id: str, include_disabled: bool = True) -> list[MemoryItem]:
        items = self._store.list_memory(project_id)
        if include_disabled:
            return items
        return [i for i in items if i.enabled]

    def update_content(self, item_id: str, content: str, confidence: float | None = None) -> None:
        item = self._store.get_memory(item_id)
        if item is None:
            raise ValueError(f"Unknown memory item: {item_id}")
        item.content = content.strip()
        if confidence is not None:
            item.confidence = confidence
        item.updated_at = _now()
        self._store.update_memory(item)

    def set_enabled(self, item_id: str, enabled: bool) -> None:
        item = self._store.get_memory(item_id)
        if item is None:
            raise ValueError(f"Unknown memory item: {item_id}")
        item.enabled = enabled
        item.updated_at = _now()
        self._store.update_memory(item)

    def delete(self, item_id: str) -> None:
        self._store.delete_memory(item_id)

    def retrieve(self, project_id: str, query: str, limit: int = 5) -> list[MemoryItem]:
        """Return enabled items most relevant to ``query`` by keyword overlap.

        High-confidence architecture decisions and workflow rules get a small
        boost so durable conventions surface even on a loose keyword match.
        """

        query_tokens = _tokens(query)
        scored: list[tuple[float, MemoryItem]] = []
        for item in self._store.list_memory(project_id):
            if not item.enabled:
                continue
            overlap = len(query_tokens & _tokens(item.content))
            if overlap == 0:
                continue
            boost = 0.0
            if item.category in (
                MemoryCategory.ARCHITECTURE_DECISION,
                MemoryCategory.WORKFLOW_RULE,
            ):
                boost = 0.5 * item.confidence
            scored.append((overlap + boost, item))

        scored.sort(key=lambda t: (-t[0], -t[1].confidence))
        return [item for _, item in scored[:limit]]


def _tokens(text: str) -> set[str]:
    return {
        m.group(0).lower()
        for m in _TOKEN_RE.finditer(text)
        if m.group(0).lower() not in _STOPWORDS
    }
