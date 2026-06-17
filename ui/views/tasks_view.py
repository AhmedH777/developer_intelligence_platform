"""Tasks page: create a task, generate a grounded plan, approve or reject it.

Thin control plane — all logic lives in TaskService and PlanWorkflow.
"""

from __future__ import annotations

import streamlit as st

from dip.core.models import StoredPlan, Task, TaskState
from dip.workflows.plan import PlanGenerationError
from ui.state import get_active_project_id, get_container

_TERMINAL = {TaskState.PLAN_APPROVED, TaskState.CANCELLED}


def render() -> None:
    st.header("Tasks")
    container = get_container()
    project_id = get_active_project_id()
    if not project_id:
        st.info("Select or register a project in Settings to begin.")
        return

    with st.expander("New task", expanded=False):
        with st.form("new_task"):
            title = st.text_input("Title (optional)")
            request = st.text_area("Feature request or bug report", height=120)
            submitted = st.form_submit_button("Create task")
        if submitted and request.strip():
            task = container.tasks.create_task(project_id, title, request)
            st.session_state["active_task_id"] = task.id
            st.success(f"Created task: {task.title}")

    tasks = container.tasks.list_tasks(project_id)
    if not tasks:
        st.caption("No tasks yet. Create one above.")
        return

    labels = {t.id: f"[{t.state.value}] {t.title}" for t in tasks}
    ids = list(labels.keys())
    active = st.session_state.get("active_task_id")
    index = ids.index(active) if active in ids else 0
    selected = st.selectbox("Task", ids, index=index, format_func=lambda tid: labels[tid])
    st.session_state["active_task_id"] = selected

    task = container.tasks.get_task(selected)
    _render_task(container, task)


def _render_task(container, task: Task) -> None:
    st.subheader(task.title)
    st.caption(f"State: **{task.state.value}**")

    plan = container.plan.get_latest_plan(task.id)
    tab_request, tab_plan, tab_context, tab_events = st.tabs(
        ["Request", "Plan", "Context", "Event history"]
    )

    with tab_request:
        st.write(task.request)
        col1, col2 = st.columns(2)
        with col1:
            label = "Generate plan" if plan is None else "Re-generate plan"
            disabled = task.state in _TERMINAL
            if st.button(label, type="primary", disabled=disabled):
                _generate(container, task)
        with col2:
            if task.state not in _TERMINAL and st.button("Cancel task"):
                container.tasks.transition(task.id, TaskState.CANCELLED, "Cancelled by user")
                st.rerun()

    with tab_plan:
        if plan is None:
            st.caption("No plan yet. Generate one from the Request tab.")
        else:
            _render_plan(container, task, plan)

    with tab_context:
        if plan is None:
            st.caption("Context is compiled when a plan is generated.")
        else:
            _render_context(plan)

    with tab_events:
        for event in container.tasks.list_events(task.id):
            ts = event.created_at.strftime("%H:%M:%S")
            st.markdown(f"`{ts}` **{event.event_type}** — {event.message}")


def _generate(container, task: Task) -> None:
    with st.spinner("Compiling context and asking the model for a plan…"):
        try:
            container.plan.generate_plan(task.id)
        except PlanGenerationError as exc:
            st.error(f"Plan generation failed (task marked FAILED): {exc}")
            return
        except Exception as exc:  # connection/model errors
            st.error(f"Plan generation error: {exc}")
            return
    st.rerun()


def _render_plan(container, task: Task, plan: StoredPlan) -> None:
    p = plan.plan
    if not plan.grounding.all_grounded:
        st.warning(
            "Some cited files were not found in the index: "
            + ", ".join(plan.grounding.ungrounded_paths)
        )
    if plan.repaired:
        st.caption("⚠️ Model output needed one repair pass to validate.")

    st.markdown(f"**Goal:** {p.goal}")
    if p.acceptance_criteria:
        st.markdown("**Acceptance criteria**")
        for c in p.acceptance_criteria:
            st.markdown(f"- {c}")
    if p.relevant_architecture:
        st.markdown(f"**Architecture:** {p.relevant_architecture}")

    _file_list("Files to inspect", p.files_to_inspect)
    _file_list("Files likely to change", p.files_likely_to_change)
    _bullets("Tests to add", p.tests_to_add)
    _bullets("Risks", p.risks)
    _bullets("Assumptions", p.assumptions)
    _bullets("Open questions", p.open_questions)
    st.caption(f"Model: {plan.model}")

    if task.state == TaskState.PLANNED:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Approve plan", type="primary"):
                container.plan.approve(task.id)
                st.rerun()
        with col2:
            if st.button("❌ Reject plan"):
                container.plan.reject(task.id)
                st.rerun()
    elif task.state == TaskState.PLAN_APPROVED:
        st.success("Plan approved.")
    elif task.state == TaskState.PLAN_REJECTED:
        st.info("Plan rejected. Re-generate from the Request tab to try again.")

    with st.expander("Raw model output"):
        st.code(plan.raw_response or "(empty)")


def _render_context(plan: StoredPlan) -> None:
    ctx = plan.context
    st.caption(
        f"{len(ctx.source_regions)} evidence region(s), ~{ctx.token_estimate} tokens."
    )
    for region in ctx.source_regions:
        st.markdown(
            f"**{region.relative_path}** (L{region.start_line}-{region.end_line}) — "
            f"_{region.reason}_"
        )
        st.code(region.content, language="python")
    for note in ctx.notes:
        st.caption(note)


def _file_list(label: str, refs) -> None:
    if not refs:
        return
    st.markdown(f"**{label}**")
    for ref in refs:
        mark = "✓" if ref.exists else ("✗" if ref.exists is False else "•")
        st.markdown(f"- {mark} `{ref.path}` — {ref.reason}")


def _bullets(label: str, items: list[str]) -> None:
    if not items:
        return
    st.markdown(f"**{label}**")
    for item in items:
        st.markdown(f"- {item}")
