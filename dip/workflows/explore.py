"""Explore workflow: read-only, evidence-linked repository explanation.

Compiles a context package for a selected symbol, sends it to the local model,
and returns the explanation together with the exact context that produced it.
No files are modified.
"""

from __future__ import annotations

from dip.context.compiler import ContextCompiler
from dip.core.models import Explanation
from dip.llm.client import LLMClient
from dip.llm.prompts import build_explain_messages
from dip.repository.repository_service import RepositoryService


class ExploreWorkflow:
    def __init__(
        self,
        repository: RepositoryService,
        compiler: ContextCompiler,
        llm: LLMClient,
    ) -> None:
        self._repo = repository
        self._compiler = compiler
        self._llm = llm

    def explain_symbol(self, project_id: str, symbol_id: str) -> Explanation:
        symbol = self._repo.get_symbol(symbol_id)
        if symbol is None:
            raise ValueError(f"Unknown symbol: {symbol_id}")

        context = self._compiler.build_explain_context(project_id, symbol)
        messages = build_explain_messages(context)
        response = self._llm.generate(messages)

        return Explanation(
            project_id=project_id,
            symbol_id=symbol_id,
            text=response.text,
            context=context,
            model=response.model,
            raw_response=response.raw,
        )
