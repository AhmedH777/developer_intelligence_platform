"""Debug workflow: turn a traceback/failure into a grounded diagnosis.

The traceback is parsed deterministically into frames; frames inside the project
root are marked as repository frames and their source is pulled into context. The
model then produces ranked hypotheses (with confidence and evidence), a minimal
fix, a regression test, and a verification plan.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from dip.context.compiler import ContextCompiler
from dip.core.models import (
    DebugAnalysis,
    StoredDebugReport,
    TracebackFrame,
)
from dip.core.tasks import TaskService
from dip.llm.client import LLMClient
from dip.llm.prompts import build_debug_messages
from dip.llm.structured import generate_structured
from dip.storage.repo import Store
from dip.tools.traceback_parser import ParsedTraceback, parse_traceback


class DebugWorkflow:
    def __init__(
        self,
        store: Store,
        tasks: TaskService,
        compiler: ContextCompiler,
        llm: LLMClient,
    ) -> None:
        self._store = store
        self._tasks = tasks
        self._compiler = compiler
        self._llm = llm

    def analyze(self, project_id: str, input_text: str, task_id: str | None = None) -> StoredDebugReport:
        parsed = parse_traceback(input_text)
        frames = self._classify_frames(project_id, parsed)

        context = self._compiler.build_debug_context(project_id, frames, input_text)
        frames_text = _frames_text(frames)
        messages = build_debug_messages(
            context, parsed.exception_type, parsed.exception_message, frames_text
        )
        result = generate_structured(self._llm, messages, DebugAnalysis)
        analysis = result.value or DebugAnalysis(
            summary=f"Could not produce a structured diagnosis: {result.error}"
        )

        report = StoredDebugReport(
            id=str(uuid.uuid4()),
            task_id=task_id,
            input_text=input_text,
            exception_type=parsed.exception_type,
            exception_message=parsed.exception_message,
            frames=frames,
            analysis=analysis,
            context=context,
            model=result.model,
            raw_response=result.raw_text,
            repaired=result.repaired,
        )
        if task_id is not None:
            self._store.insert_debug_report(report)
            n = len(report.project_frames)
            self._tasks.record_event(
                task_id,
                "debug",
                f"Debug analysis: {len(analysis.hypotheses)} hypotheses, "
                f"{n} in-project frame(s).",
            )
        return report

    def latest(self, task_id: str) -> StoredDebugReport | None:
        return self._store.get_latest_debug_report(task_id)

    def _classify_frames(self, project_id: str, parsed: ParsedTraceback) -> list[TracebackFrame]:
        project = self._store.get_project(project_id)
        assert project is not None
        root = Path(project.root_path).resolve()

        frames: list[TracebackFrame] = []
        for raw in parsed.frames:
            in_project = False
            relative: str | None = None
            try:
                resolved = Path(raw.file_path).resolve()
                rel = resolved.relative_to(root)
                # Exclude virtualenv/site-packages living under the root.
                parts = set(rel.parts)
                if not parts & {".venv", "venv", "site-packages"}:
                    in_project = True
                    relative = rel.as_posix()
            except (ValueError, OSError):
                pass
            frames.append(
                TracebackFrame(
                    file_path=raw.file_path,
                    line=raw.line,
                    function=raw.function,
                    code=raw.code,
                    in_project=in_project,
                    relative_path=relative,
                )
            )
        return frames


def _frames_text(frames: list[TracebackFrame]) -> str:
    lines = []
    for f in frames:
        marker = "[project] " if f.in_project else "[external] "
        loc = f.relative_path or f.file_path
        lines.append(f"{marker}{loc}:{f.line} in {f.function}() -> {f.code}")
    return "\n".join(lines) if lines else "(no frames parsed)"
