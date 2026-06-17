"""Tests page: run the verification pipeline for the active task and show results.

Verification runs cheapest-first over the files the patch changed. A blocking
failure (syntax or tests) prevents the task from being accepted on the Changes
page.
"""

from __future__ import annotations

import streamlit as st

from dip.core.models import TaskState, VerificationStatus
from ui.state import get_active_project_id, get_container

_ICON = {
    VerificationStatus.PASS: "🟢",
    VerificationStatus.FAIL: "🔴",
    VerificationStatus.NOT_VERIFIED: "⚪",
    VerificationStatus.MANUAL_CHECK_REQUIRED: "🟡",
}


def render() -> None:
    st.header("Tests & Verification")
    container = get_container()
    if not get_active_project_id():
        st.info("Select or register a project in Settings to begin.")
        return

    task_id = st.session_state.get("active_task_id")
    if not task_id:
        st.info("Select a task on the Tasks page first.")
        return

    task = container.tasks.get_task(task_id)
    st.subheader(task.title)
    st.caption(f"State: **{task.state.value}**")

    application = container.implement.get_latest_application(task_id)
    can_verify = task.state in (TaskState.APPLIED, TaskState.DONE) and application is not None
    if not can_verify:
        st.info("Apply a patch (Changes page) before running verification.")

    if can_verify and st.button("Run verification", type="primary"):
        with st.spinner("Running checks (syntax → lint → types → tests)…"):
            container.verification.verify_task(task_id)
        st.rerun()

    run = container.verification.latest(task_id)
    if run is None:
        st.caption("No verification run yet.")
        return

    overall = run.status
    st.markdown(f"### Overall: {_ICON[overall]} **{overall.value}**")
    if overall == VerificationStatus.FAIL:
        st.error("Blocking checks failed — completing the task is blocked on the Changes page.")

    for step in run.steps:
        icon = _ICON[step.status]
        blocking = " · blocking" if step.blocking else ""
        with st.expander(
            f"{icon} {step.name} — {step.status.value} ({step.summary}){blocking}",
            expanded=step.status == VerificationStatus.FAIL,
        ):
            st.caption(f"`{step.command}`  ·  exit={step.exit_code}  ·  {step.duration_seconds:.2f}s")
            for d in step.diagnostics:
                loc = f"{d.file_path}:{d.line}" if d.file_path else ""
                code = f" [{d.code}]" if d.code else ""
                st.markdown(f"- **{d.severity}** {loc}{code} — {d.message}")
