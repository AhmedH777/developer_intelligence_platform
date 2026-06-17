"""Architecture page: rules, current violations, and the internal import graph."""

from __future__ import annotations

import streamlit as st

from ui.state import get_active_project_id, get_container


def render() -> None:
    st.header("Architecture")
    container = get_container()
    project_id = get_active_project_id()
    if not project_id:
        st.info("Select or register a project in Settings to begin.")
        return

    st.subheader("Rules")
    rules = container.architecture.rules
    if not rules:
        st.caption("No architecture rules configured.")
    for rule in rules:
        scope = rule.applies_to or "(whole repo)"
        st.markdown(
            f"- **{rule.name}** — under `{scope}`, must not import "
            f"{', '.join('`'+f+'`' for f in rule.forbidden_imports)}. {rule.description}"
        )

    st.subheader("Violations")
    violations = container.architecture.check_project(project_id)
    if not violations:
        st.success("No architecture violations across the indexed repository.")
    else:
        for v in violations:
            st.error(f"`{v.file_path}` imports `{v.imported_module}` — breaks **{v.rule_name}**")

    st.subheader("Internal import graph")
    edges = container.architecture.internal_edges(project_id)
    if not edges:
        st.caption("No internal imports detected.")
        return
    dot = _build_dot(edges)
    try:
        st.graphviz_chart(dot)
    except Exception:
        st.caption("Graphviz unavailable; showing edges as a list.")
        for src, dst in edges:
            st.markdown(f"- `{src}` → `{dst}`")


def _build_dot(edges: list[tuple[str, str]]) -> str:
    lines = ["digraph imports {", "  rankdir=LR;", '  node [shape=box, fontsize=10];']
    for src, dst in sorted(set(edges)):
        lines.append(f'  "{src}" -> "{dst}";')
    lines.append("}")
    return "\n".join(lines)
