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
        _render_repair(container, task_id, task.state)

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

    # The outcome of the most recent repair is shown regardless of current status,
    # so a successful repair's summary doesn't disappear when checks go green.
    _render_repair_result(task_id)


def _render_repair(container, task_id: str, task_state) -> None:
    if task_state != TaskState.APPLIED:
        return
    st.markdown("#### Bounded auto-repair")
    limit = container.settings.safety.max_repair_attempts
    st.caption(
        f"Attempts at most {limit} fixes, each snapshotted and re-verified. A new "
        "hypothesis is required per attempt; scope expansion and test changes need approval."
    )
    col1, col2 = st.columns(2)
    allow_scope = col1.checkbox("Allow scope expansion")
    allow_tests = col2.checkbox("Allow test changes")
    if st.button("Run auto-repair", type="primary"):
        with st.spinner("Attempting bounded repair…"):
            result = container.repair.run(
                task_id, allow_scope_expansion=allow_scope, allow_test_changes=allow_tests
            )
        st.session_state["last_repair"] = result.model_dump()
        st.rerun()


def _render_repair_result(task_id: str) -> None:
    repair = st.session_state.get("last_repair")
    if not repair or repair["task_id"] != task_id:
        return
    status, msg = repair["status"], repair["message"]
    st.markdown("#### Last repair")
    if status == "fixed":
        st.success(f"Repair: {msg}")
    elif status == "needs_approval":
        st.warning(f"Repair paused: {msg}")
    else:
        st.info(f"Repair {status}: {msg}")
    for a in repair["attempts"]:
        tag = "✅" if a["applied"] else "•"
        st.markdown(
            f"{tag} attempt {a['attempt']}: _{a['hypothesis']}_ → "
            f"{a['verification_status']} {('('+a['note']+')') if a['note'] else ''}"
        )
