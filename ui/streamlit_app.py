"""Streamlit entry point.

Thin control plane: it renders widgets and delegates every action to the
``dip`` services via the container. No parsing, persistence, or model calls
happen here.

Run with:  streamlit run ui/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `streamlit run ui/streamlit_app.py` from the repo root to import `dip`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from ui.state import get_active_project_id, get_container  # noqa: E402
from ui.views import repository_view, settings_view, tasks_view  # noqa: E402

st.set_page_config(page_title="Developer Intelligence Platform", layout="wide")


def _sidebar() -> str:
    container = get_container()
    st.sidebar.title("Dev Intelligence")

    projects = container.projects.list_projects()
    if projects:
        labels = {p.id: f"{p.name}" for p in projects}
        active = get_active_project_id()
        ids = list(labels.keys())
        index = ids.index(active) if active in ids else 0
        chosen = st.sidebar.selectbox(
            "Active project",
            ids,
            index=index,
            format_func=lambda pid: labels[pid],
        )
        st.session_state["active_project_id"] = chosen
        project = container.projects.get_project(chosen)
        st.sidebar.caption(f"Path: {project.root_path}")
        if project.git_branch:
            st.sidebar.caption(f"Branch: {project.git_branch}")
        st.sidebar.caption(f"Symbols indexed: {container.store.count_symbols(chosen)}")
    else:
        st.sidebar.info("No projects yet. Add one in Settings.")

    return st.sidebar.radio("Page", ["Repository", "Tasks", "Settings"], index=0)


def main() -> None:
    page = _sidebar()
    if page == "Settings":
        settings_view.render()
    elif page == "Tasks":
        tasks_view.render()
    else:
        repository_view.render()


main()
