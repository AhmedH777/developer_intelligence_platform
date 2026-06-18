"""Settings page: register repositories and view configuration."""

from __future__ import annotations

import streamlit as st

from dip.llm.router import ALL_ROLES, LLMRouter
from ui.state import (
    drop_container,
    get_active_repo_path,
    get_container,
    get_registry,
    get_settings,
    set_active_repo_path,
)


def render() -> None:
    st.header("Settings")
    registry = get_registry()

    st.subheader("Register a Python repository")
    st.caption(
        "Each repo stores its own data in a gitignored `<repo>/.dip/` folder, so "
        "memory and history travel with the repository."
    )
    with st.form("register_repo"):
        path = st.text_input("Absolute path to the repository root")
        name = st.text_input("Display name (optional)")
        submitted = st.form_submit_button("Register & index")
    if submitted and path.strip():
        try:
            entry = registry.register(path, name=name or None)
        except ValueError as exc:
            st.error(str(exc))
        else:
            set_active_repo_path(entry.path)
            container = get_container()
            with st.spinner("Indexing repository…"):
                result = container.index.index_project(container.project_id)
            st.success(
                f"Registered '{entry.name}'. Indexed {result.files_indexed} files / "
                f"{result.symbols_indexed} symbols into {entry.path}/.dip."
            )
            if result.errors:
                with st.expander(f"{len(result.errors)} file(s) skipped"):
                    for err in result.errors:
                        st.text(err)

    st.divider()
    st.subheader("Registered repositories")
    entries = registry.list()
    if not entries:
        st.caption("None yet.")
    for entry in entries:
        cols = st.columns([4, 1])
        active = " ✅ active" if entry.path == get_active_repo_path() else ""
        cols[0].write(f"- **{entry.name}**{active} — `{entry.path}`")
        if cols[1].button("Remove", key=f"rm_{entry.path}"):
            registry.remove(entry.path)
            drop_container(entry.path)
            if get_active_repo_path() == entry.path:
                set_active_repo_path(None)
            st.rerun()

    # Configuration display reflects the active repo if one is selected (so
    # per-repo .devintel.yaml overrides are visible), else the global defaults.
    container = get_container()
    settings = container.settings if container else get_settings()
    router = container.router if container else LLMRouter(settings.llm)

    st.divider()
    st.subheader("Local LLM endpoint")
    llm = settings.llm
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
        "Set these in a gitignored `.env` file, `config/settings.yaml`, or via "
        "`DIP_LLM_*` env vars. Per-repo overrides go in `<repo>/.devintel.yaml`. "
        "Restart to apply."
    )

    st.subheader("Model routing by role")
    st.write(
        {role: dict(zip(("model", "temperature"), router.resolved_model(role)))
         for role in ALL_ROLES}
    )

    st.subheader("Auto-pilot")
    orch = settings.orchestrator
    st.write(
        {
            "approval gates": orch.gates,
            "auto_repair": orch.auto_repair,
            "auto_accept_on_pass": orch.auto_accept_on_pass,
        }
    )

    st.subheader("Architecture rules")
    for rule in settings.architecture.rules:
        st.write(f"- **{rule.name}** (under `{rule.applies_to or '/'}`): no "
                 f"{', '.join(rule.forbidden_imports)}")
