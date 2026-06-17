"""Settings page: register a repository and view the active LLM configuration."""

from __future__ import annotations

import streamlit as st

from dip.core.projects import ProjectError
from ui.state import get_container, set_active_project_id


def render() -> None:
    st.header("Settings")
    container = get_container()

    st.subheader("Register a Python repository")
    with st.form("register_project"):
        path = st.text_input("Absolute path to the repository root")
        name = st.text_input("Display name (optional)")
        submitted = st.form_submit_button("Register & index")
    if submitted:
        try:
            project = container.projects.register_project(path, name=name or None)
        except ProjectError as exc:
            st.error(str(exc))
        else:
            with st.spinner("Indexing repository…"):
                result = container.index.index_project(project.id)
            set_active_project_id(project.id)
            st.success(
                f"Registered '{project.name}'. Indexed {result.files_indexed} files / "
                f"{result.symbols_indexed} symbols."
            )
            if result.errors:
                with st.expander(f"{len(result.errors)} file(s) skipped"):
                    for err in result.errors:
                        st.text(err)

    st.divider()
    st.subheader("Local LLM endpoint (read-only view)")
    llm = container.settings.llm
    st.write(
        {
            "base_url": llm.base_url,
            "model": llm.model,
            "temperature": llm.temperature,
            "max_tokens": llm.max_tokens,
            "context_char_budget": llm.context_char_budget,
        }
    )
    st.caption(
        "Edit these in config/settings.yaml or via DIP_LLM_* environment variables, "
        "then restart the app."
    )

    st.divider()
    st.subheader("Registered projects")
    for project in container.projects.list_projects():
        st.write(f"- **{project.name}** — `{project.root_path}`")
