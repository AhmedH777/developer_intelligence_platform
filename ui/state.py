"""UI-side helpers for holding the service container in Streamlit session state.

The container owns a SQLite connection, so it is cached per Streamlit session
via ``st.session_state`` rather than rebuilt on every rerun. This module is the
only place the UI reaches into ``dip`` wiring.
"""

from __future__ import annotations

import streamlit as st

from dip.container import Container
from dip.core.config import load_settings


def get_container() -> Container:
    if "container" not in st.session_state:
        st.session_state["container"] = Container.create(settings=load_settings())
    return st.session_state["container"]


def get_active_project_id() -> str | None:
    return st.session_state.get("active_project_id")


def set_active_project_id(project_id: str | None) -> None:
    st.session_state["active_project_id"] = project_id
