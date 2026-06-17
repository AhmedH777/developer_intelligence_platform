"""UI-side helpers for the registry and per-repo containers.

Each registered repository has its own ``<repo>/.dip`` store. The UI tracks the
active repo path and caches one ``Container`` per repo (each owns a SQLite
connection), rebuilt lazily across Streamlit reruns. This module is the only
place the UI reaches into ``dip`` wiring.
"""

from __future__ import annotations

import streamlit as st

from dip.container import Container
from dip.core.config import load_settings
from dip.core.registry import Registry


def get_settings():
    if "settings" not in st.session_state:
        st.session_state["settings"] = load_settings()
    return st.session_state["settings"]


def get_registry() -> Registry:
    if "registry" not in st.session_state:
        st.session_state["registry"] = Registry(get_settings().registry_path)
    return st.session_state["registry"]


def get_active_repo_path() -> str | None:
    return st.session_state.get("active_repo_path")


def set_active_repo_path(path: str | None) -> None:
    st.session_state["active_repo_path"] = path


def get_container() -> Container | None:
    """Return the container bound to the active repo, or None if none selected."""

    path = get_active_repo_path()
    if not path:
        return None
    cache = st.session_state.setdefault("containers", {})
    if path not in cache:
        cache[path] = Container.for_repo(path, base_settings=get_settings())
    return cache[path]


def drop_container(path: str) -> None:
    cache = st.session_state.get("containers", {})
    cache.pop(path, None)


def get_active_project_id() -> str | None:
    container = get_container()
    return container.project_id if container else None
