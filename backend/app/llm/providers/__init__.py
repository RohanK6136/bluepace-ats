from __future__ import annotations

from app.llm.providers.base import Provider
from app.llm.types import ModelProfile


def make_provider(profile: ModelProfile, json_instruction: str) -> Provider:
    if profile.provider == "openai_compatible":
        from app.llm.providers.openai_compat import OpenAICompatibleProvider

        return OpenAICompatibleProvider(profile, json_instruction)
    if profile.provider == "anthropic":
        from app.llm.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(profile, json_instruction)
    raise ValueError(f"unknown provider {profile.provider!r}")
