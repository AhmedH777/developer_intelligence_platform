"""Composition root.

Builds and wires the service graph from a ``Settings`` object and a database
connection. Both the Streamlit UI and the tests construct services through here,
so wiring lives in exactly one place. This module imports no UI framework.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from dip.context.compiler import ContextCompiler
from dip.core.config import Settings, load_repo_settings, load_settings
from dip.core.jobs import JobService
from dip.core.memory import MemoryService
from dip.core.projects import ProjectService
from dip.core.tasks import TaskService
from dip.skills.loader import SkillLoader
from dip.llm.client import LLMClient
from dip.llm import router as roles
from dip.llm.router import LLMRouter
from dip.repository.architecture import ArchitectureService
from dip.repository.index_service import IndexService
from dip.repository.repository_service import RepositoryService
from dip.storage.database import connect
from dip.storage.repo import Store
from dip.tools.commands import CommandRunner
from dip.tools.literature import NullLiteratureProvider, OpenAlexLiteratureProvider
from dip.tools.patch import PatchService
from dip.workflows.debug import DebugWorkflow
from dip.workflows.explore import ExploreWorkflow
from dip.workflows.implement import ImplementWorkflow
from dip.workflows.orchestrator import Orchestrator
from dip.workflows.plan import PlanWorkflow
from dip.workflows.repair import RepairWorkflow
from dip.workflows.research import ResearchWorkflow
from dip.workflows.review import ReviewWorkflow
from dip.workflows.verify import VerificationService


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
        self.memory = MemoryService(self.store)
        self.skills = SkillLoader()
        # Set by ``for_repo`` when the container is bound to a single repo.
        self.project = None
        self.project_id: str | None = None
        # Per-role routing. A test-injected ``llm`` is returned for every role.
        self.router = LLMRouter(settings.llm, override=llm)
        self.llm: LLMClient = self.router.for_role(roles.CODER)
        self.compiler = ContextCompiler(
            self.repository, char_budget=settings.llm.context_char_budget
        )
        self.patches = PatchService(settings.safety)
        self.command_runner = CommandRunner(settings.commands)
        self.jobs = JobService(self.store, self.command_runner, settings)
        self.architecture = ArchitectureService(self.store, settings.architecture)
        self.verification = VerificationService(
            self.store, self.tasks, self.command_runner, settings, architecture=self.architecture
        )
        self.explore = ExploreWorkflow(
            self.repository, self.compiler, self.router.for_role(roles.EXPLAINER)
        )
        self.plan = PlanWorkflow(
            self.store, self.tasks, self.compiler,
            self.router.for_role(roles.PLANNER), memory=self.memory, skills=self.skills,
        )
        self.implement = ImplementWorkflow(
            self.store,
            self.tasks,
            self.compiler,
            self.patches,
            self.index,
            self.router.for_role(roles.CODER),
            verification=self.verification,
            block_on_failed_verification=settings.commands.block_completion_on_failed_verification,
        )
        self.debug = DebugWorkflow(
            self.store, self.tasks, self.compiler, self.router.for_role(roles.DEBUGGER)
        )
        self.review = ReviewWorkflow(
            self.store, self.tasks, self.compiler, self.router.for_role(roles.REVIEWER)
        )
        self.repair = RepairWorkflow(
            self.store,
            self.tasks,
            self.compiler,
            self.patches,
            self.index,
            self.verification,
            self.router.for_role(roles.CODER),
            settings,
        )
        self.orchestrator = Orchestrator(
            self.tasks,
            self.plan,
            self.implement,
            self.verification,
            self.repair,
            settings.orchestrator,
        )
        # Literature provider: offline by default; OpenAlex when enabled per-repo.
        self.literature = (
            OpenAlexLiteratureProvider(mailto=settings.research.literature_mailto)
            if settings.research.literature
            else NullLiteratureProvider()
        )
        self.research = ResearchWorkflow(
            self.store,
            self.tasks,
            self.repository,
            self.compiler,
            self.router.for_role(roles.RESEARCHER),
            settings,
            memory=self.memory,
            skills=self.skills,
            literature=self.literature,
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

    @classmethod
    def for_repo(
        cls,
        repo_path: Path | str,
        base_settings: Settings | None = None,
        llm: LLMClient | None = None,
    ) -> "Container":
        """Build a container bound to one repo, storing data in ``<repo>/.dip``.

        Applies the repo's ``.devintel.yaml`` overrides, keeps the store inside
        the repo (gitignored via a self-ignore file), and registers the repo as
        the store's single project so data persists in the repo across sessions.
        """

        root = Path(repo_path).expanduser().resolve()
        base = base_settings or load_settings()
        settings = load_repo_settings(base, root)
        settings = settings.model_copy(update={"storage_dir": root / ".dip"})

        conn = connect(settings.database_path)
        _ensure_self_ignore(settings.storage_dir)
        container = cls(settings, conn, llm=llm)

        project = container.projects.register_project(root)
        container.project = project
        container.project_id = project.id
        return container


def _ensure_self_ignore(dip_dir: Path) -> None:
    """Write a ``.gitignore`` (``*``) inside ``.dip`` so git ignores the folder."""

    dip_dir.mkdir(parents=True, exist_ok=True)
    gitignore = dip_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")
