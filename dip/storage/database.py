"""SQLite connection management and schema initialisation.

The schema is intentionally small for the first slice (projects, files,
symbols). Hand-written SQL keeps persistence transparent and inspectable, which
matches the platform's deterministic ethos. Future milestones add tables for
tasks, plans, patches, and verification runs.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    root_path   TEXT NOT NULL UNIQUE,
    git_branch  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repository_files (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    mtime         REAL NOT NULL,
    language      TEXT NOT NULL DEFAULT 'python',
    indexed_at    TEXT NOT NULL,
    UNIQUE (project_id, relative_path)
);

CREATE TABLE IF NOT EXISTS repository_symbols (
    id               TEXT PRIMARY KEY,
    project_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_id          TEXT NOT NULL REFERENCES repository_files(id) ON DELETE CASCADE,
    relative_path    TEXT NOT NULL,
    kind             TEXT NOT NULL,
    name             TEXT NOT NULL,
    qualified_name   TEXT NOT NULL,
    start_line       INTEGER NOT NULL,
    end_line         INTEGER NOT NULL,
    signature        TEXT,
    docstring        TEXT,
    parent_symbol_id TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    request     TEXT NOT NULL,
    state       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_events (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    message     TEXT NOT NULL,
    data        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS plans (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    model       TEXT NOT NULL,
    repaired    INTEGER NOT NULL DEFAULT 0,
    plan_json   TEXT NOT NULL,
    grounding_json TEXT NOT NULL,
    context_json   TEXT NOT NULL,
    raw_response   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_files_project ON repository_files(project_id);
CREATE INDEX IF NOT EXISTS idx_symbols_project ON repository_symbols(project_id);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON repository_symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON repository_symbols(project_id, name);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id);
CREATE INDEX IF NOT EXISTS idx_plans_task ON plans(task_id);
"""


def connect(database_path: Path | str) -> sqlite3.Connection:
    """Open a SQLite connection with sensible defaults and the schema applied."""

    path = Path(database_path)
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False: Streamlit may run reruns of one session on
    # different threads, and the connection is cached in session state. Access is
    # serialized per session (no concurrent writers), so this is safe here.
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA)
    return conn
