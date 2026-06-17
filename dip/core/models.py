"""Pydantic domain models shared across services and the UI.

These are the typed contracts the plan calls for. Persistence (``dip.storage``)
maps them to/from SQLite rows; the UI renders them directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

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


# ----- Tasks & planning (Milestone 2) ---------------------------------------


class TaskState(str, Enum):
    NEW = "new"
    INVESTIGATING = "investigating"
    PLANNED = "planned"  # plan generated, awaiting user approval
    PLAN_APPROVED = "plan_approved"
    PLAN_REJECTED = "plan_rejected"
    PATCH_PROPOSED = "patch_proposed"  # patch generated, awaiting approval
    APPLIED = "applied"  # patch applied to disk
    ROLLED_BACK = "rolled_back"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


# Allowed state transitions. Verification states arrive in a later milestone.
TASK_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.NEW: {TaskState.INVESTIGATING, TaskState.CANCELLED},
    TaskState.INVESTIGATING: {TaskState.PLANNED, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.PLANNED: {
        TaskState.PLAN_APPROVED,
        TaskState.PLAN_REJECTED,
        TaskState.CANCELLED,
    },
    TaskState.PLAN_REJECTED: {TaskState.INVESTIGATING, TaskState.CANCELLED},
    TaskState.PLAN_APPROVED: {
        TaskState.PATCH_PROPOSED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    # PATCH_PROPOSED -> PLAN_APPROVED means "reject patch / regenerate".
    TaskState.PATCH_PROPOSED: {
        TaskState.APPLIED,
        TaskState.PLAN_APPROVED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.APPLIED: {TaskState.DONE, TaskState.ROLLED_BACK, TaskState.CANCELLED},
    TaskState.ROLLED_BACK: {
        TaskState.PATCH_PROPOSED,
        TaskState.PLAN_APPROVED,
        TaskState.CANCELLED,
    },
    TaskState.DONE: {TaskState.CANCELLED},
    TaskState.FAILED: {
        TaskState.INVESTIGATING,
        TaskState.PLAN_APPROVED,
        TaskState.CANCELLED,
    },
    TaskState.CANCELLED: set(),
}


class Task(BaseModel):
    id: str
    project_id: str
    title: str
    request: str
    state: TaskState = TaskState.NEW
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class TaskEvent(BaseModel):
    id: str
    task_id: str
    created_at: datetime = Field(default_factory=_now)
    event_type: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class PlanFileRef(BaseModel):
    path: str
    reason: str = ""
    # Set during grounding validation: does this path exist in the index?
    exists: bool | None = None


class ImplementationPlan(BaseModel):
    """Structured plan the model must return (the plan's §13.2 shape)."""

    goal: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    relevant_architecture: str = ""
    files_to_inspect: list[PlanFileRef] = Field(default_factory=list)
    files_likely_to_change: list[PlanFileRef] = Field(default_factory=list)
    tests_to_add: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class PlanGrounding(BaseModel):
    """Which cited files actually exist in the indexed repository."""

    grounded_paths: list[str] = Field(default_factory=list)
    ungrounded_paths: list[str] = Field(default_factory=list)

    @property
    def all_grounded(self) -> bool:
        return not self.ungrounded_paths


class StoredPlan(BaseModel):
    id: str
    task_id: str
    plan: ImplementationPlan
    grounding: PlanGrounding
    context: ContextPackage
    model: str
    created_at: datetime = Field(default_factory=_now)
    raw_response: str = ""
    repaired: bool = False


# ----- Patch generation & application (Milestone 3) -------------------------


class SearchReplaceEdit(BaseModel):
    """One Aider-style edit: replace an exact ``search`` block with ``replace``.

    An empty ``search`` means "create a new file" whose content is ``replace``.
    """

    path: str
    search: str
    replace: str


class PatchProposal(BaseModel):
    """Structured patch the model must return — no raw file writes by the model."""

    summary: str
    rationale: str = ""
    edits: list[SearchReplaceEdit] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class FileChange(BaseModel):
    """A single file's computed before/after plus a unified diff for display."""

    path: str
    change_type: Literal["modify", "create"]
    original: str
    updated: str
    diff: str
    applicable: bool
    issues: list[str] = Field(default_factory=list)


class PatchPreview(BaseModel):
    """Validated, displayable view of a proposal before it is applied."""

    file_changes: list[FileChange] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)

    @property
    def safe(self) -> bool:
        return not self.blocking_issues and all(c.applicable for c in self.file_changes)

    @property
    def combined_diff(self) -> str:
        return "\n".join(c.diff for c in self.file_changes if c.diff)


class StoredPatchProposal(BaseModel):
    id: str
    task_id: str
    proposal: PatchProposal
    preview: PatchPreview
    context: ContextPackage
    model: str
    created_at: datetime = Field(default_factory=_now)
    raw_response: str = ""
    repaired: bool = False


class PatchApplication(BaseModel):
    id: str
    task_id: str
    proposal_id: str
    status: Literal["applied", "rolled_back", "failed"]
    changed_files: list[str] = Field(default_factory=list)
    # path -> original content, or None if the file did not exist (was created).
    snapshot: dict[str, str | None] = Field(default_factory=dict)
    diff: str = ""
    created_at: datetime = Field(default_factory=_now)


# ----- Commands, jobs & verification (Milestone 4) --------------------------


class CommandSpec(BaseModel):
    """A structured command — never a raw shell string (the plan's §15.1)."""

    executable: str
    arguments: list[str] = Field(default_factory=list)
    working_directory: str
    timeout_seconds: int = 300

    @property
    def display(self) -> str:
        return " ".join([self.executable, *self.arguments])


class CommandResult(BaseModel):
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(BaseModel):
    id: str
    project_id: str
    job_type: str
    idempotency_key: str
    status: JobStatus = JobStatus.QUEUED
    command: CommandSpec
    log_path: str
    exit_code: int | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Diagnostic(BaseModel):
    """A single tool finding (lint error, type error, test failure)."""

    tool: str
    file_path: str | None = None
    line: int | None = None
    severity: str = "error"
    code: str | None = None
    message: str = ""


class VerificationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_VERIFIED = "not_verified"  # tool unavailable / nothing to check
    MANUAL_CHECK_REQUIRED = "manual_check_required"


class VerificationStep(BaseModel):
    name: str
    command: str
    status: VerificationStatus
    duration_seconds: float = 0.0
    exit_code: int | None = None
    blocking: bool = True
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    summary: str = ""


class VerificationRun(BaseModel):
    id: str
    task_id: str
    created_at: datetime = Field(default_factory=_now)
    steps: list[VerificationStep] = Field(default_factory=list)

    @property
    def status(self) -> VerificationStatus:
        if any(s.status == VerificationStatus.FAIL and s.blocking for s in self.steps):
            return VerificationStatus.FAIL
        if any(s.status == VerificationStatus.PASS for s in self.steps):
            return VerificationStatus.PASS
        return VerificationStatus.NOT_VERIFIED

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.PASS


# ----- Debugging & review (Milestone 5) -------------------------------------


class TracebackFrame(BaseModel):
    file_path: str
    line: int
    function: str
    code: str = ""
    in_project: bool = False
    relative_path: str | None = None


class DebugHypothesis(BaseModel):
    description: str
    confidence: Literal["low", "medium", "high"] = "medium"
    evidence: str = ""


class DebugAnalysis(BaseModel):
    """Model output for a debug request — frames are supplied deterministically."""

    summary: str
    hypotheses: list[DebugHypothesis] = Field(default_factory=list)
    suggested_inspection: list[str] = Field(default_factory=list)
    minimal_fix: str = ""
    regression_test: str = ""
    verification_plan: list[str] = Field(default_factory=list)


class StoredDebugReport(BaseModel):
    id: str
    task_id: str | None = None
    input_text: str
    exception_type: str | None = None
    exception_message: str = ""
    frames: list[TracebackFrame] = Field(default_factory=list)
    analysis: DebugAnalysis
    context: ContextPackage
    model: str
    created_at: datetime = Field(default_factory=_now)
    raw_response: str = ""
    repaired: bool = False

    @property
    def project_frames(self) -> list[TracebackFrame]:
        return [f for f in self.frames if f.in_project]


class ReviewFinding(BaseModel):
    severity: Literal["info", "warning", "error", "critical"] = "warning"
    category: str = "correctness"
    file_path: str = ""
    start_line: int | None = None
    end_line: int | None = None
    title: str
    explanation: str = ""
    recommendation: str = ""


class ReviewResult(BaseModel):
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)


class StoredReview(BaseModel):
    id: str
    task_id: str | None = None
    target: str
    result: ReviewResult
    context: ContextPackage
    model: str
    created_at: datetime = Field(default_factory=_now)
    raw_response: str = ""
    repaired: bool = False


FileTreeNode.model_rebuild()
