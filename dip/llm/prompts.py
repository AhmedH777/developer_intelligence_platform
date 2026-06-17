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


PLAN_SYSTEM = (
    "You are a senior engineer producing a grounded implementation plan for a "
    "Python repository. You work only from the provided repository evidence.\n"
    "Rules:\n"
    "- Do not invent files, modules, symbols, or APIs. Only reference paths and "
    "symbols that appear in the evidence, or clearly new files you propose to "
    "create (mark these in the reason).\n"
    "- Keep the plan minimal and concrete.\n"
    "- Do NOT write the full implementation code; describe what changes are needed.\n"
    "- Respond with a single JSON object only — no prose, no markdown fences."
)

PLAN_JSON_TEMPLATE = """{
  "goal": "one-sentence statement of what to achieve",
  "acceptance_criteria": ["testable condition", "..."],
  "relevant_architecture": "short note on how this fits the existing code",
  "files_to_inspect": [{"path": "pkg/module.py", "reason": "why"}],
  "files_likely_to_change": [{"path": "pkg/module.py", "reason": "why"}],
  "tests_to_add": ["description of a test to add or update"],
  "risks": ["risk or edge case"],
  "assumptions": ["assumption made"],
  "open_questions": ["question for the user"]
}"""


IMPLEMENT_SYSTEM = (
    "You are a careful Python engineer producing a minimal patch as a set of "
    "exact search/replace edits. You never write files directly.\n"
    "Rules:\n"
    "- For each edit, the `search` text MUST be copied verbatim from the provided "
    "file content, including indentation, and must be unique within that file.\n"
    "- Keep `search` blocks small but large enough to be unambiguous.\n"
    "- To create a new file, use an empty `search` and put the full file content "
    "in `replace`.\n"
    "- Make the smallest change that satisfies the request. Do not reformat "
    "unrelated code.\n"
    "- Only edit files present in the evidence (or new files you clearly intend "
    "to create).\n"
    "- Respond with a single JSON object only — no prose, no markdown fences."
)

PATCH_JSON_TEMPLATE = """{
  "summary": "one-line summary of the change",
  "rationale": "why this change satisfies the request",
  "edits": [
    {"path": "pkg/module.py", "search": "exact text to find", "replace": "new text"}
  ],
  "risks": ["risk or follow-up to check"]
}"""


def build_implement_messages(context: ContextPackage, plan_goal: str = "") -> list[Message]:
    evidence_blocks: list[str] = []
    for region in context.source_regions:
        header = f"File: {region.relative_path} (full content, {region.end_line} lines)"
        evidence_blocks.append(f"{header}\n```python\n{region.content}\n```")
    evidence = "\n\n".join(evidence_blocks) if evidence_blocks else "(no files provided)"

    goal_line = f"Approved plan goal: {plan_goal}\n\n" if plan_goal else ""
    user = (
        f"Request:\n{context.user_request}\n\n"
        f"{goal_line}"
        f"Current file content (author search blocks to match this exactly):\n\n"
        f"{evidence}\n\n"
        "Return a patch as a JSON object with exactly this shape:\n"
        f"{PATCH_JSON_TEMPLATE}"
    )
    return [
        Message(role="system", content=IMPLEMENT_SYSTEM),
        Message(role="user", content=user),
    ]


def build_plan_messages(context: ContextPackage) -> list[Message]:
    evidence_blocks: list[str] = []
    for region in context.source_regions:
        header = (
            f"File: {region.relative_path} "
            f"(lines {region.start_line}-{region.end_line}, {region.kind}"
            + (f", symbol {region.symbol}" if region.symbol else "")
            + ")"
        )
        evidence_blocks.append(f"{header}\n```python\n{region.content}\n```")
    evidence = "\n\n".join(evidence_blocks) if evidence_blocks else "(no matching code found)"

    user = (
        f"Feature/bug request:\n{context.user_request}\n\n"
        f"Repository evidence:\n\n{evidence}\n\n"
        "Produce an implementation plan as a JSON object with exactly this shape:\n"
        f"{PLAN_JSON_TEMPLATE}"
    )
    return [Message(role="system", content=PLAN_SYSTEM), Message(role="user", content=user)]
