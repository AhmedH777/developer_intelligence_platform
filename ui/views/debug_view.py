"""Debug page: paste a traceback/failure and get a grounded diagnosis."""

from __future__ import annotations

import streamlit as st

from ui.state import get_active_project_id, get_container

_CONF_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def render() -> None:
    st.header("Debug")
    container = get_container()
    project_id = get_active_project_id()
    if not project_id:
        st.info("Select or register a project in Settings to begin.")
        return

    task_id = st.session_state.get("active_task_id")
    st.caption(
        "Paste a traceback, test failure, or error log. Frames inside this "
        "project are identified and their source is sent to the model."
    )

    prefill = _prefill_from_verification(container, task_id)
    text = st.text_area("Traceback / failure", value=prefill, height=220, key="debug_input")

    if st.button("Analyze", type="primary", disabled=not text.strip()):
        with st.spinner("Parsing frames and diagnosing…"):
            try:
                report = container.debug.analyze(project_id, text, task_id=task_id)
            except Exception as exc:
                st.error(f"Debug failed: {exc}")
                return
        st.session_state["last_debug"] = report.model_dump()

    report = st.session_state.get("last_debug")
    if report:
        _render_report(report)


def _prefill_from_verification(container, task_id) -> str:
    if not task_id:
        return ""
    run = container.verification.latest(task_id)
    if run is None:
        return ""
    for step in run.steps:
        if step.status.value == "fail" and step.diagnostics:
            return "\n".join(d.message for d in step.diagnostics if d.message)
    return ""


def _render_report(report: dict) -> None:
    exc = report.get("exception_type")
    if exc:
        st.markdown(f"**Exception:** `{exc}: {report.get('exception_message', '')}`")

    frames = report.get("frames", [])
    project_frames = [f for f in frames if f.get("in_project")]
    st.markdown(f"**Repository frames identified:** {len(project_frames)} of {len(frames)}")
    for f in frames:
        tag = "🟦 project" if f.get("in_project") else "⬜ external"
        loc = f.get("relative_path") or f.get("file_path")
        st.markdown(f"- {tag} `{loc}:{f['line']}` in `{f['function']}()` — {f.get('code','')}")

    analysis = report["analysis"]
    st.markdown(f"### Diagnosis\n{analysis['summary']}")

    if analysis["hypotheses"]:
        st.markdown("**Ranked hypotheses**")
        for h in analysis["hypotheses"]:
            icon = _CONF_ICON.get(h.get("confidence", "medium"), "🟠")
            st.markdown(f"- {icon} **{h['confidence']}** — {h['description']}")
            if h.get("evidence"):
                st.caption(f"evidence: {h['evidence']}")

    _bullets("Suggested inspection", analysis.get("suggested_inspection", []))
    if analysis.get("minimal_fix"):
        st.markdown(f"**Minimal fix:** {analysis['minimal_fix']}")
    if analysis.get("regression_test"):
        st.markdown(f"**Regression test:** {analysis['regression_test']}")
    _bullets("Verification plan", analysis.get("verification_plan", []))

    with st.expander("Context sent + raw output"):
        for r in report["context"]["source_regions"]:
            st.markdown(f"**{r['relative_path']}** (L{r['start_line']}-{r['end_line']})")
            st.code(r["content"], language="python")
        st.code(report.get("raw_response", "") or "(empty)")


def _bullets(label: str, items: list) -> None:
    if not items:
        return
    st.markdown(f"**{label}**")
    for item in items:
        st.markdown(f"- {item}")
