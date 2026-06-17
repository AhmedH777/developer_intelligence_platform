"""Memory page: browse/manage project memory and view repository skills."""

from __future__ import annotations

import streamlit as st

from dip.core.models import MemoryCategory
from ui.state import get_active_project_id, get_container


def render() -> None:
    st.header("Memory & Skills")
    container = get_container()
    project_id = get_active_project_id()
    if not project_id:
        st.info("Select or register a project in Settings to begin.")
        return

    mem_tab, skills_tab = st.tabs(["Memory", "Skills"])
    with mem_tab:
        _render_memory(container, project_id)
    with skills_tab:
        _render_skills(container, project_id)


def _render_memory(container, project_id: str) -> None:
    with st.expander("Add a memory item", expanded=False):
        with st.form("add_memory"):
            category = st.selectbox(
                "Category", [c.value for c in MemoryCategory], format_func=lambda v: v
            )
            content = st.text_area("Content", height=80)
            confidence = st.slider("Confidence", 0.0, 1.0, 0.8, 0.05)
            task_id = st.session_state.get("active_task_id")
            link_task = st.checkbox(
                "Attribute to the active task", value=bool(task_id), disabled=not task_id
            )
            submitted = st.form_submit_button("Add")
        if submitted and content.strip():
            container.memory.add(
                project_id,
                MemoryCategory(category),
                content,
                source_task_id=task_id if (link_task and task_id) else None,
                confidence=confidence,
            )
            st.success("Memory item added.")
            st.rerun()

    items = container.memory.list(project_id)
    if not items:
        st.caption("No memory yet. Add durable project facts, decisions, or known failures.")
        return

    for item in items:
        state = "🟢" if item.enabled else "⚪"
        with st.expander(f"{state} [{item.category.value}] {item.content[:70]}"):
            new_content = st.text_area("Content", value=item.content, key=f"c_{item.id}")
            new_conf = st.slider("Confidence", 0.0, 1.0, float(item.confidence), 0.05, key=f"k_{item.id}")
            src = item.source_task_id or "—"
            st.caption(f"Source task: {src}  ·  created {item.created_at:%Y-%m-%d}")
            cols = st.columns(3)
            with cols[0]:
                if st.button("Save", key=f"s_{item.id}"):
                    container.memory.update_content(item.id, new_content, confidence=new_conf)
                    st.rerun()
            with cols[1]:
                label = "Disable" if item.enabled else "Enable"
                if st.button(label, key=f"e_{item.id}"):
                    container.memory.set_enabled(item.id, not item.enabled)
                    st.rerun()
            with cols[2]:
                if st.button("Delete", key=f"d_{item.id}"):
                    container.memory.delete(item.id)
                    st.rerun()


def _render_skills(container, project_id: str) -> None:
    project = container.projects.get_project(project_id)
    skills = container.skills.load(project.root_path)
    skills_dir = container.skills.skills_dir(project.root_path)
    st.caption(f"Skills are markdown files in `{skills_dir}` inside the repository.")
    if not skills:
        st.info("No skill files found. Add `*.md` files describing repository-specific tasks.")
        return
    for skill in skills:
        with st.expander(f"📘 {skill.name}"):
            if skill.purpose:
                st.markdown(skill.purpose)
            for heading, body in skill.sections.items():
                st.markdown(f"**{heading}**")
                st.markdown(body)
            st.caption(skill.path)
