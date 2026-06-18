"""Execution page: run a safe, allowlisted command as a background job.

Commands run as OS subprocesses tracked by the JobService, so they survive
Streamlit reruns and stream output to a log file. Idempotency keys prevent a
double-click (or a rerun) from launching duplicate jobs.
"""

from __future__ import annotations

import shlex

import streamlit as st

from dip.core.models import CommandSpec, JobStatus
from ui.state import get_active_project_id, get_container

_PRESETS = {
    "pytest -q": ("pytest", ["-q"]),
    "ruff check .": ("ruff", ["check", "."]),
    "mypy .": ("mypy", ["."]),
    "python --version": ("python", ["--version"]),
}
_ACTIVE = {JobStatus.QUEUED, JobStatus.RUNNING}


def render() -> None:
    st.header("Execution")
    container = get_container()
    project_id = get_active_project_id()
    if not project_id:
        st.info("Select or register a project in Settings to begin.")
        return

    project = container.projects.get_project(project_id)

    preset = st.selectbox("Command preset", list(_PRESETS.keys()))
    executable, base_args = _PRESETS[preset]
    extra = st.text_input("Extra arguments (optional)")
    args = base_args + (shlex.split(extra) if extra.strip() else [])

    spec = CommandSpec(
        executable=executable,
        arguments=args,
        working_directory=project.root_path,
        timeout_seconds=container.settings.commands.default_timeout_seconds,
    )
    st.caption(f"Will run: `{spec.display}` in `{project.root_path}`")

    if st.button("Run", type="primary"):
        try:
            job = container.jobs.enqueue_command(
                project_id, "command", spec, idempotency_key=f"{project_id}:{spec.display}"
            )
            st.session_state["active_job_id"] = job.id
        except Exception as exc:
            st.error(f"Could not start command: {exc}")

    _render_active_job(container)

    st.divider()
    st.subheader("Recent jobs")
    for job in container.jobs.list_jobs(project_id, limit=10):
        st.markdown(f"`{job.status.value}` — **{job.command.display}** ({job.job_type})")


def _render_active_job(container) -> None:
    job_id = st.session_state.get("active_job_id")
    if not job_id:
        return
    job = container.jobs.poll(job_id)  # advance state if the process has exited

    st.divider()
    cols = st.columns([2, 1, 1])
    cols[0].markdown(f"**{job.command.display}**")
    cols[1].markdown(f"Status: `{job.status.value}`")
    if job.status in _ACTIVE:
        if cols[2].button("Cancel"):
            container.jobs.cancel(job.id)
            st.rerun()
        st.button("Refresh logs")  # triggers a rerun to re-poll
    else:
        st.caption(f"Exit code: {job.exit_code}")

    log = container.jobs.read_log(job)
    st.code(log or "(no output yet)")
