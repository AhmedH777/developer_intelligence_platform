"""Changes page: generate a patch, review the diff, apply or roll back.

Shown per active task. The model proposes search/replace edits; this page
renders the computed diff and gates application on the safety preview.
"""

from __future__ import annotations

import streamlit as st

from dip.core.models import StoredPatchProposal, Task, TaskState, VerificationStatus
from dip.tools.patch import PatchError
from dip.workflows.implement import CompletionBlockedError, PatchGenerationError
from ui.state import get_active_project_id, get_container

_CAN_GENERATE = {TaskState.PLAN_APPROVED, TaskState.ROLLED_BACK}


def render() -> None:
    st.header("Changes")
    container = get_container()
    project_id = get_active_project_id()
    if not project_id:
        st.info("Select or register a project in Settings to begin.")
        return

    task_id = st.session_state.get("active_task_id")
    if not task_id:
        st.info("Select a task on the Tasks page first.")
        return

    task = container.tasks.get_task(task_id)
    st.subheader(task.title)
    st.caption(f"State: **{task.state.value}**")

    if task.state in _CAN_GENERATE:
        label = "Generate patch"
        proposal = container.implement.get_latest_proposal(task_id)
        if st.button(label, type="primary"):
            _generate(container, task)
    elif task.state in (TaskState.NEW, TaskState.PLANNED, TaskState.PLAN_REJECTED):
        st.info("Approve a plan on the Tasks page before generating a patch.")

    proposal = container.implement.get_latest_proposal(task_id)
    if proposal is None:
        return

    _render_proposal(container, task, proposal)


def _generate(container, task: Task) -> None:
    with st.spinner("Generating patch from the approved plan…"):
        try:
            container.implement.generate_patch(task.id)
        except PatchGenerationError as exc:
            st.error(f"Patch generation failed (task marked FAILED): {exc}")
            return
        except Exception as exc:
            st.error(f"Patch generation error: {exc}")
            return
    st.rerun()


def _render_proposal(container, task: Task, proposal: StoredPatchProposal) -> None:
    p = proposal.proposal
    preview = proposal.preview

    st.markdown(f"**Summary:** {p.summary}")
    if p.rationale:
        st.caption(p.rationale)
    if proposal.repaired:
        st.caption("⚠️ Model output needed one repair pass to validate.")
    if p.risks:
        st.markdown("**Risks**")
        for r in p.risks:
            st.markdown(f"- {r}")

    if preview.blocking_issues:
        for issue in preview.blocking_issues:
            st.error(issue)

    for change in preview.file_changes:
        icon = "🟢" if change.applicable else "🔴"
        st.markdown(f"{icon} **{change.path}** — _{change.change_type}_")
        for issue in change.issues:
            st.warning(issue)
        if change.diff:
            st.code(change.diff, language="diff")

    st.divider()

    if task.state == TaskState.PATCH_PROPOSED:
        if not preview.safe:
            st.error("This patch is not applicable as-is. Reject and regenerate.")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Apply patch", type="primary", disabled=not preview.safe):
                _apply(container, task, proposal)
        with col2:
            if st.button("❌ Reject patch"):
                container.implement.reject_patch(task.id)
                st.rerun()
    elif task.state == TaskState.APPLIED:
        st.success("Patch applied.")
        verification = container.verification.latest(task.id)
        if verification is None:
            st.info("Run verification on the Tests page before accepting.")
        elif verification.status == VerificationStatus.FAIL:
            st.error("Verification failed — accept is blocked (override below if intentional).")
        elif verification.status == VerificationStatus.PASS:
            st.success("Verification passed.")

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Accept change", type="primary"):
                _accept(container, task, override=False)
        with col2:
            if st.button("↩️ Roll back"):
                with st.spinner("Restoring files…"):
                    container.implement.rollback(task.id)
                st.rerun()
        with col3:
            if st.button("Override & accept"):
                _accept(container, task, override=True)
    elif task.state == TaskState.DONE:
        st.success("Change accepted. Task done.")
    elif task.state == TaskState.ROLLED_BACK:
        st.info("Patch rolled back. You can regenerate a patch above.")

    with st.expander("Raw model output"):
        st.code(proposal.raw_response or "(empty)")


def _apply(container, task: Task, proposal: StoredPatchProposal) -> None:
    with st.spinner("Snapshotting and applying…"):
        try:
            container.implement.apply_patch(task.id, proposal.id)
        except PatchError as exc:
            st.error(f"Apply blocked: {exc}")
            return
    st.rerun()


def _accept(container, task: Task, override: bool) -> None:
    try:
        container.implement.accept(task.id, override=override)
    except CompletionBlockedError as exc:
        st.error(str(exc))
        return
    st.rerun()
