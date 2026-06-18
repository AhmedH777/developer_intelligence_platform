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


DEBUG_SYSTEM = (
    "You are a debugging assistant. You diagnose a failure using only the "
    "traceback and the repository source provided.\n"
    "Rules:\n"
    "- Ground every hypothesis in the provided frames/source; cite file and "
    "function in the `evidence` field. Do not invent code.\n"
    "- Rank hypotheses most-likely first and give each a confidence of low, "
    "medium, or high.\n"
    "- Propose the smallest plausible fix and a regression test that would catch "
    "the bug.\n"
    "- Respond with a single JSON object only — no prose, no markdown fences."
)

DEBUG_JSON_TEMPLATE = """{
  "summary": "what went wrong, in one or two sentences",
  "hypotheses": [
    {"description": "...", "confidence": "high", "evidence": "file.py:func - why"}
  ],
  "suggested_inspection": ["what to print/log/check next"],
  "minimal_fix": "the smallest change that would likely fix it",
  "regression_test": "a test that would catch this bug",
  "verification_plan": ["command or check to confirm the fix"]
}"""


def build_debug_messages(
    context: ContextPackage, exception_type: str | None, exception_message: str, frames_text: str
) -> list[Message]:
    evidence_blocks: list[str] = []
    for region in context.source_regions:
        header = (
            f"File: {region.relative_path} (lines {region.start_line}-{region.end_line}, "
            f"function {region.symbol})"
        )
        evidence_blocks.append(f"{header}\n```python\n{region.content}\n```")
    evidence = "\n\n".join(evidence_blocks) if evidence_blocks else "(no in-project source)"

    exc = f"{exception_type}: {exception_message}" if exception_type else "(unparsed failure)"
    user = (
        f"Failure / traceback:\n{context.user_request}\n\n"
        f"Exception: {exc}\n\n"
        f"Repository frames (most recent call last):\n{frames_text}\n\n"
        f"Source around the in-project frames:\n\n{evidence}\n\n"
        "Diagnose the failure as a JSON object with exactly this shape:\n"
        f"{DEBUG_JSON_TEMPLATE}"
    )
    return [Message(role="system", content=DEBUG_SYSTEM), Message(role="user", content=user)]


REVIEW_SYSTEM = (
    "You are a code reviewer. Review the change described by the diff, using the "
    "provided file content as ground truth.\n"
    "Consider these categories: correctness, regression risk, missing tests, "
    "architecture, error handling, performance, security, readability.\n"
    "Rules:\n"
    "- Every finding must cite a real file path and, where possible, line numbers "
    "from the provided content. Do not invent code.\n"
    "- Use severity one of: info, warning, error, critical.\n"
    "- If the change looks fine, return an empty findings list with a short "
    "summary.\n"
    "- Respond with a single JSON object only — no prose, no markdown fences."
)

REVIEW_JSON_TEMPLATE = """{
  "summary": "overall assessment in one or two sentences",
  "findings": [
    {"severity": "warning", "category": "correctness", "file_path": "pkg/m.py",
     "start_line": 12, "end_line": 14, "title": "short title",
     "explanation": "what is wrong and why", "recommendation": "how to fix"}
  ]
}"""


def build_review_messages(context: ContextPackage) -> list[Message]:
    evidence_blocks: list[str] = []
    for region in context.source_regions:
        header = f"File: {region.relative_path} (resulting content, {region.end_line} lines)"
        evidence_blocks.append(f"{header}\n```python\n{region.content}\n```")
    evidence = "\n\n".join(evidence_blocks) if evidence_blocks else "(no file content)"

    user = (
        f"Change under review (unified diff):\n```diff\n{context.user_request}\n```\n\n"
        f"Resulting file content:\n\n{evidence}\n\n"
        "Review the change and return a JSON object with exactly this shape:\n"
        f"{REVIEW_JSON_TEMPLATE}"
    )
    return [Message(role="system", content=REVIEW_SYSTEM), Message(role="user", content=user)]


REPAIR_SYSTEM = (
    "You are fixing a failing change. You are given the current file content and "
    "the verification failure. Propose the smallest search/replace edits that "
    "make the checks pass.\n"
    "Rules:\n"
    "- State a clear `hypothesis` for the root cause. It MUST be different from "
    "any previously-tried hypothesis listed.\n"
    "- `search` text must be copied verbatim from the current content and be "
    "unique in its file.\n"
    "- Do not weaken or delete tests. Do not install dependencies. Keep the change "
    "minimal.\n"
    "- Respond with a single JSON object only — no prose, no markdown fences."
)

REPAIR_JSON_TEMPLATE = """{
  "hypothesis": "root-cause hypothesis (must be new)",
  "summary": "what this fix does",
  "edits": [{"path": "pkg/module.py", "search": "exact text", "replace": "new text"}],
  "risks": ["risk"]
}"""


def build_repair_messages(
    context: ContextPackage, failure_text: str, previous_hypotheses: list[str]
) -> list[Message]:
    evidence_blocks: list[str] = []
    for region in context.source_regions:
        header = f"File: {region.relative_path} (current content, {region.end_line} lines)"
        evidence_blocks.append(f"{header}\n```python\n{region.content}\n```")
    evidence = "\n\n".join(evidence_blocks) if evidence_blocks else "(no files provided)"

    prior = (
        "Previously-tried hypotheses (do not repeat):\n"
        + "\n".join(f"- {h}" for h in previous_hypotheses)
        + "\n\n"
        if previous_hypotheses
        else ""
    )
    user = (
        f"Original request:\n{context.user_request}\n\n"
        f"Verification failure:\n{failure_text}\n\n"
        f"{prior}"
        f"Current file content:\n\n{evidence}\n\n"
        "Return a repair as a JSON object with exactly this shape:\n"
        f"{REPAIR_JSON_TEMPLATE}"
    )
    return [Message(role="system", content=REPAIR_SYSTEM), Message(role="user", content=user)]


RESEARCH_SYSTEM = (
    "You are a research engineer proposing concrete, runnable experiments for a "
    "specific codebase, given a research direction.\n"
    "Rules:\n"
    "- Ground every proposal in the repository's actual capabilities (from the "
    "capability digest). `affected_paths` must reference real files from the "
    "digest, or clearly new files you propose to create (note that in the reason).\n"
    "- Each proposal must be a concrete experiment: a hypothesis, the change/method "
    "to implement, variants/ablations, and an evaluation (metrics + baselines).\n"
    "- Respect project memory: do NOT re-propose known failures; build on prior "
    "findings.\n"
    "- Only put items in `related_work` if they appear in the provided literature.\n"
    "- Respond with a single JSON object only — no prose, no markdown fences."
)

RESEARCH_JSON_TEMPLATE = """{
  "summary": "one or two sentences framing the proposed agenda",
  "proposals": [
    {
      "title": "short title",
      "hypothesis": "what you expect and why",
      "motivation": "why it matters for the direction",
      "method": "what to implement/change to run it",
      "affected_paths": [{"path": "pkg/module.py", "reason": "why"}],
      "variants": ["ablation or sweep"],
      "evaluation": "metrics, baselines, success criteria",
      "baselines": ["baseline to compare against"],
      "risks": ["risk"],
      "effort": "low|medium|high",
      "novelty": "low|medium|high",
      "expected_impact": "low|medium|high",
      "related_work": []
    }
  ]
}"""


def build_research_messages(
    context: ContextPackage,
    direction: str,
    capability_digest: str,
    literature: list | None = None,
    max_proposals: int = 5,
) -> list[Message]:
    memory_block = ""
    if context.memory_items:
        bullets = "\n".join(f"- {m}" for m in context.memory_items)
        memory_block = f"Project memory (respect known failures, build on findings):\n{bullets}\n\n"

    skills_block = ""
    if context.skills:
        skills_block = "Repository skills (playbooks):\n\n" + "\n\n".join(context.skills) + "\n\n"

    lit_block = ""
    if literature:
        lines = "\n".join(f"- {item.citation}" for item in literature)
        lit_block = f"Relevant literature (cite these in related_work when used):\n{lines}\n\n"

    user = (
        f"Research direction:\n{direction or '(none given — infer promising directions from the repo)'}\n\n"
        f"Repository capability digest:\n{capability_digest}\n\n"
        f"{memory_block}{skills_block}{lit_block}"
        f"Propose up to {max_proposals} experiments as a JSON object with exactly this shape:\n"
        f"{RESEARCH_JSON_TEMPLATE}"
    )
    return [Message(role="system", content=RESEARCH_SYSTEM), Message(role="user", content=user)]


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

    memory_block = ""
    if context.memory_items:
        bullets = "\n".join(f"- {m}" for m in context.memory_items)
        memory_block = (
            "Project memory & conventions (honor these unless the request "
            f"overrides them):\n{bullets}\n\n"
        )

    skills_block = ""
    if context.skills:
        skills_block = (
            "Repository skills (playbooks to follow when relevant):\n\n"
            + "\n\n".join(context.skills)
            + "\n\n"
        )

    user = (
        f"Feature/bug request:\n{context.user_request}\n\n"
        f"{memory_block}"
        f"{skills_block}"
        f"Repository evidence:\n\n{evidence}\n\n"
        "Produce an implementation plan as a JSON object with exactly this shape:\n"
        f"{PLAN_JSON_TEMPLATE}"
    )
    return [Message(role="system", content=PLAN_SYSTEM), Message(role="user", content=user)]
