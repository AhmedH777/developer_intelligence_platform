"""Prompt construction for workflows.

Prompts are built from a context package so the model only ever sees the
evidence the UI also displays. The explain prompt forbids inventing files or
symbols and asks the model to separate verified facts from inference, matching
the plan's grounding requirements.
"""

from __future__ import annotations

from dip.core.models import ContextPackage
from dip.llm.client import Message

EXPLAIN_SYSTEM = (
    "You are a precise code-explanation assistant working strictly from the "
    "repository evidence provided. Rules:\n"
    "- Only describe code that appears in the provided source. Do not invent "
    "files, symbols, functions, or behavior.\n"
    "- When you reference code, cite the file path and the symbol name.\n"
    "- Clearly separate what the code definitely does (verifiable from the "
    "source) from anything you are inferring.\n"
    "- If the provided context is insufficient to answer, say so explicitly."
)


def build_explain_messages(context: ContextPackage) -> list[Message]:
    evidence_blocks: list[str] = []
    for region in context.source_regions:
        header = (
            f"File: {region.relative_path} "
            f"(lines {region.start_line}-{region.end_line}, {region.kind}"
            + (f", symbol {region.symbol}" if region.symbol else "")
            + ")"
        )
        evidence_blocks.append(f"{header}\n```python\n{region.content}\n```")

    evidence = "\n\n".join(evidence_blocks) if evidence_blocks else "(no source provided)"

    user = (
        f"Task: {context.user_request}\n\n"
        f"Repository evidence:\n\n{evidence}\n\n"
        "Explain the selected code based only on this evidence."
    )
    return [Message(role="system", content=EXPLAIN_SYSTEM), Message(role="user", content=user)]
