"""Review page: structured findings on the active task's latest patch."""

from __future__ import annotations

import streamlit as st

from dip.workflows.review import ReviewError
from ui.state import get_active_project_id, get_container

_SEV_ICON = {"info": "🔵", "warning": "🟠", "error": "🔴", "critical": "🟥"}
_SEV_ORDER = {"critical": 0, "error": 1, "warning": 2, "info": 3}


def render() -> None:
    st.header("Review")
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
    proposal = container.implement.get_latest_proposal(task_id)
    if proposal is None:
        st.info("Generate a patch (Changes page) before reviewing.")
        return

    st.caption(f"Reviewing the latest patch: {proposal.proposal.summary}")
    if st.button("Review patch", type="primary"):
        with st.spinner("Reviewing the change…"):
            try:
                container.review.review_latest_patch(task_id)
            except ReviewError as exc:
                st.error(str(exc))
                return
            except Exception as exc:
                st.error(f"Review failed: {exc}")
                return
        st.rerun()

    review = container.review.latest(task_id)
    if review is None:
        st.caption("No review yet.")
        return

    st.markdown(f"### Summary\n{review.result.summary}")
    findings = sorted(
        review.result.findings, key=lambda f: _SEV_ORDER.get(f.severity, 9)
    )
    if not findings:
        st.success("No findings — the change looks clean.")
    for f in findings:
        icon = _SEV_ICON.get(f.severity, "🟠")
        loc = f"{f.file_path}:{f.start_line}" if f.start_line else f.file_path
        with st.expander(f"{icon} [{f.severity}] {f.category} — {f.title}  ({loc})"):
            st.markdown(f"**Where:** `{loc}`")
            if f.explanation:
                st.markdown(f"**Why:** {f.explanation}")
            if f.recommendation:
                st.markdown(f"**Fix:** {f.recommendation}")
    st.caption(f"Model: {review.model}")
