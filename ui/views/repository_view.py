"""Repository page: browse files & symbols, then explain a selected symbol.

Layout: file list | code + symbols | explanation + the exact context sent.
"""

from __future__ import annotations

import streamlit as st

from dip.core.models import FileTreeNode
from ui.state import get_active_project_id, get_container


def _flatten_files(node: FileTreeNode, acc: list[str]) -> None:
    if not node.is_dir and node.path:
        acc.append(node.path)
    for child in node.children:
        _flatten_files(child, acc)


def render() -> None:
    st.header("Repository")
    container = get_container()
    project_id = get_active_project_id()

    if not project_id:
        st.info("Select or register a project in Settings to begin.")
        return

    tree = container.repository.get_file_tree(project_id)
    files: list[str] = []
    _flatten_files(tree, files)
    if not files:
        st.warning("No indexed Python files. Re-register the project in Settings.")
        return

    left, middle, right = st.columns([1.1, 1.7, 2.2])

    with left:
        st.subheader("Files")
        query = st.text_input("Search files / symbols", key="repo_search")
        if query:
            for result in container.repository.search(project_id, query)[:25]:
                label = result.symbol.qualified_name if result.symbol else result.relative_path
                st.caption(f"{result.kind}: {label} — _{result.reason}_")
        selected_file = st.radio("File", files, key="repo_selected_file")

    source = container.repository.get_file(project_id, selected_file)

    with middle:
        st.subheader(selected_file)
        st.code(source.content, language="python", line_numbers=True)

    with right:
        st.subheader("Symbols")
        if not source.symbols:
            st.caption("No symbols in this file.")
            return

        options = {
            f"{s.kind.value}: {s.qualified_name}  (L{s.start_line}-{s.end_line})": s.id
            for s in source.symbols
        }
        chosen_label = st.selectbox("Select a symbol", list(options.keys()))
        symbol_id = options[chosen_label]

        if st.button("Explain selected symbol", type="primary"):
            with st.spinner("Asking the local model…"):
                try:
                    explanation = container.explore.explain_symbol(project_id, symbol_id)
                except Exception as exc:  # surface connection/model errors plainly
                    st.error(f"Explain failed: {exc}")
                    return
            st.session_state["last_explanation"] = explanation.model_dump()

        explanation = st.session_state.get("last_explanation")
        if explanation and explanation["symbol_id"] == symbol_id:
            st.markdown("#### Explanation")
            st.markdown(explanation["text"])
            st.caption(f"Model: {explanation['model']}")

            ctx = explanation["context"]
            with st.expander(
                f"Context sent — {len(ctx['source_regions'])} region(s), "
                f"~{ctx['token_estimate']} tokens",
                expanded=False,
            ):
                for region in ctx["source_regions"]:
                    st.markdown(
                        f"**{region['relative_path']}** "
                        f"(L{region['start_line']}-{region['end_line']}) — "
                        f"_{region['reason']}_"
                    )
                    st.code(region["content"], language="python")
                for note in ctx["notes"]:
                    st.caption(note)
