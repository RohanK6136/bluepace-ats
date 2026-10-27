"""Glue between stages and the LLM layer: render prompt → call_with_retry, track availability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.core.errors import LLMUnavailable
from app.features.jd_standardizer.promptlib import load_prompt
from app.llm.client import CallContext, ChatLLM, LLMResult, call_with_retry, estimate_tokens


@dataclass
class StepLLM:
    llm: ChatLLM
    ctx: CallContext
    settings: Settings
    available: bool = True

    def render(self, prompt_name: str, variables: dict[str, Any]) -> tuple[str, str, int]:
        tpl = load_prompt(prompt_name)
        system, user = tpl.render(**variables)
        return system, user, tpl.version

    def fits(self, prompt_name: str, variables: dict[str, Any], max_tokens: int) -> bool:
        system, user, _ = self.render(prompt_name, variables)
        est = estimate_tokens(self.settings.CHARS_PER_TOKEN, system, user)
        return est + max_tokens <= self.llm.context_tokens(self.ctx)

    async def call(self, step: str, prompt_name: str, variables: dict[str, Any], schema: dict[str, Any],
                   max_tokens: int) -> LLMResult:
        if not self.available:
            raise LLMUnavailable("the model was unavailable earlier in this run")
        system, user, version = self.render(prompt_name, variables)
        try:
            return await call_with_retry(self.llm, self.ctx, self.settings, step, version, system, user,
                                         schema, max_tokens)
        except LLMUnavailable:
            self.available = False
            raise

    def call_ids_since(self, n: int) -> list[str]:
        return [r["id"] for r in self.ctx.records[n:]]
