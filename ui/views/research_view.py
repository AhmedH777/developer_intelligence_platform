"""Research page: propose grounded experiments and promote them to tasks."""

from __future__ import annotations

import streamlit as st

from dip.workflows.research import ResearchError
from ui.state import get_active_project_id, get_container

_LEVEL_ICON = {"high": "🟢", "medium": "🟠", "low": "⚪"}


def render() -> None:
    st.header("Research Scout")
    container = get_container()
    project_id = get_active_project_id()
    if not project_id:
        st.info("Select or register a project in Settings to begin.")
        return

    cfg = container.settings.research
    st.caption(
        "Propose grounded experiments for this repo, then promote one to a Task "
        "(which flows into the plan → patch → verify pipeline)."
    )
    direction = st.text_area(
        "Research direction", value=cfg.direction, height=80,
        help="Set a default per-repo in .devintel.yaml under `research.direction`.",
    )
    col1, col2 = st.columns(2)
    objective = col1.selectbox(
        "Rank by", ["balanced", "novelty", "impact", "feasibility"],
        index=["balanced", "novelty", "impact", "feasibility"].index(cfg.objective),
    )
    col2.caption(f"Literature: {'on' if getattr(container.literature, 'available', False) else 'offline'}")

    if st.button("Generate proposals", type="primary"):
        with st.spinner("Studying the repo and proposing experiments…"):
            try:
                container.research.propose(project_id, direction=direction, objective=objective)
            except ResearchError as exc:
                st.error(f"Proposal generation failed: {exc}")
                return
            except Exception as exc:
                st.error(f"Research error: {exc}")
                return
        st.rerun()

    run = container.research.latest(project_id)
    if run is None:
        st.caption("No proposals yet.")
        return

    if run.summary:
        st.markdown(f"**Agenda:** {run.summary}")
    st.caption(f"Direction: _{run.direction or '(inferred)'}_  ·  ranked by **{run.objective}**")

    for i, p in enumerate(run.proposals):
        header = (
            f"{_LEVEL_ICON[p.novelty]} **{p.title}** — "
            f"novelty {p.novelty} · impact {p.expected_impact} · effort {p.effort}"
        )
        with st.expander(header, expanded=(i == 0)):
            st.markdown(f"**Hypothesis:** {p.hypothesis}")
            if p.motivation:
                st.markdown(f"**Motivation:** {p.motivation}")
            if p.method:
                st.markdown(f"**Method:** {p.method}")
            if p.affected_paths:
                st.markdown("**Affected modules**")
                for ref in p.affected_paths:
                    mark = "✓" if ref.exists else ("✗ new/unknown" if ref.exists is False else "•")
                    st.markdown(f"- {mark} `{ref.path}` — {ref.reason}")
            _bullets("Variants", p.variants)
            if p.evaluation:
                st.markdown(f"**Evaluation:** {p.evaluation}")
            _bullets("Baselines", p.baselines)
            _bullets("Risks", p.risks)
            _bullets("Related work", p.related_work)
            if st.button("Promote to task", key=f"promote_{run.id}_{i}", type="primary"):
                task = container.research.promote_to_task(project_id, run.id, i)
                st.session_state["active_task_id"] = task.id
                st.success(f"Created task '{task.title}'. Open the Tasks page to plan it.")

    with st.expander("Raw model output"):
        st.code(run.raw_response or "(empty)")


def _bullets(label: str, items: list) -> None:
    if not items:
        return
    st.markdown(f"**{label}**")
    for item in items:
        st.markdown(f"- {item}")
