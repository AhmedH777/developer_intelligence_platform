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

from ui.state import (  # noqa: E402
    get_active_repo_path,
    get_container,
    get_registry,
    set_active_repo_path,
)
from ui.views import (  # noqa: E402
    architecture_view,
    changes_view,
    debug_view,
    execution_view,
    memory_view,
    repository_view,
    research_view,
    review_view,
    settings_view,
    tasks_view,
    tests_view,
)

st.set_page_config(page_title="Developer Intelligence Platform", layout="wide")


def _sidebar() -> str:
    st.sidebar.title("Dev Intelligence")

    registry = get_registry()
    entries = registry.list()
    if entries:
        paths = [e.path for e in entries]
        labels = {e.path: e.name for e in entries}
        active = get_active_repo_path()
        index = paths.index(active) if active in paths else 0
        chosen = st.sidebar.selectbox(
            "Active repository",
            paths,
            index=index,
            format_func=lambda p: labels.get(p, p),
        )
        set_active_repo_path(chosen)
        container = get_container()
        if container is not None:
            st.sidebar.caption(f"Path: {chosen}")
            if container.project and container.project.git_branch:
                st.sidebar.caption(f"Branch: {container.project.git_branch}")
            st.sidebar.caption(
                f"Symbols indexed: {container.store.count_symbols(container.project_id)}"
            )
    else:
        st.sidebar.info("No repositories yet. Register one in Settings.")

    return st.sidebar.radio(
        "Page",
        [
            "Repository",
            "Research",
            "Tasks",
            "Changes",
            "Review",
            "Tests",
            "Debug",
            "Execution",
            "Architecture",
            "Memory",
            "Settings",
        ],
        index=0,
    )


def main() -> None:
    page = _sidebar()
    # Every page except Settings needs an active repo + its container.
    if page != "Settings" and get_container() is None:
        st.info("Register and select a repository in **Settings** to begin.")
        return
    if page == "Settings":
        settings_view.render()
    elif page == "Research":
        research_view.render()
    elif page == "Tasks":
        tasks_view.render()
    elif page == "Changes":
        changes_view.render()
    elif page == "Review":
        review_view.render()
    elif page == "Tests":
        tests_view.render()
    elif page == "Debug":
        debug_view.render()
    elif page == "Execution":
        execution_view.render()
    elif page == "Architecture":
        architecture_view.render()
    elif page == "Memory":
        memory_view.render()
    else:
        repository_view.render()


main()
