"""Composition root.

Builds and wires the service graph from a ``Settings`` object and a database
connection. Both the Streamlit UI and the tests construct services through here,
so wiring lives in exactly one place. This module imports no UI framework.
"""

from __future__ import annotations

import sqlite3

from dip.context.compiler import ContextCompiler
from dip.core.config import Settings, load_settings
from dip.core.projects import ProjectService
from dip.core.tasks import TaskService
from dip.llm.client import LLMClient, OpenAICompatibleClient
from dip.repository.index_service import IndexService
from dip.repository.repository_service import RepositoryService
from dip.storage.database import connect
from dip.storage.repo import Store
from dip.tools.patch import PatchService
from dip.workflows.explore import ExploreWorkflow
from dip.workflows.implement import ImplementWorkflow
from dip.workflows.plan import PlanWorkflow


class Container:
    def __init__(
        self,
        settings: Settings,
        conn: sqlite3.Connection,
        llm: LLMClient | None = None,
    ) -> None:
        self.settings = settings
        self.connection = conn
        self.store = Store(conn)
        self.projects = ProjectService(self.store)
        self.index = IndexService(self.store, settings)
        self.repository = RepositoryService(self.store)
        self.tasks = TaskService(self.store)
        self.llm: LLMClient = llm or OpenAICompatibleClient(settings.llm)
        self.compiler = ContextCompiler(
            self.repository, char_budget=settings.llm.context_char_budget
        )
        self.patches = PatchService(settings.safety)
        self.explore = ExploreWorkflow(self.repository, self.compiler, self.llm)
        self.plan = PlanWorkflow(self.store, self.tasks, self.compiler, self.llm)
        self.implement = ImplementWorkflow(
            self.store,
            self.tasks,
            self.compiler,
            self.patches,
            self.index,
            self.llm,
        )

    @classmethod
    def create(
        cls,
        settings: Settings | None = None,
        llm: LLMClient | None = None,
    ) -> "Container":
        settings = settings or load_settings()
        conn = connect(settings.database_path)
        return cls(settings, conn, llm=llm)
