"""Model profile registry: config/models.yaml → validated ModelProfile objects.

`${VAR}` and `${VAR:-default}` are expanded from the environment, so endpoints and model ids can be set per
deployment without editing the file. API keys are referenced by env-var NAME only and never stored or returned.
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path
from typing import Any

import yaml

from app.core.errors import LLMConfigError
from app.llm.types import ModelProfile, ProfileStatus

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1)) or (m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


class ModelRegistry:
    def __init__(self, profiles: list[ModelProfile], default_id: str, json_instruction: str):
        if not profiles:
            raise LLMConfigError("no model profiles configured")
        self._profiles = {p.id: p for p in profiles}
        if default_id not in self._profiles:
            raise LLMConfigError(f"default profile {default_id!r} is not defined")
        self.default_id = default_id
        self.json_instruction = json_instruction

    @classmethod
    def from_file(cls, path: Path, default_override: str | None = None) -> ModelRegistry:
        data = _expand(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        defaults = data.get("defaults") or {}
        profiles = [ModelProfile(id=pid, **{**defaults.get("profile", {}), **(spec or {})})
                    for pid, spec in (data.get("profiles") or {}).items()]
        return cls(profiles, default_override or data.get("default_profile", ""),
                   defaults.get("json_instruction", "Return JSON only, matching this JSON schema exactly:"))

    @classmethod
    def single(cls, profile: ModelProfile) -> ModelRegistry:
        return cls([profile], profile.id, "Return JSON only, matching this JSON schema exactly:")

    # ------------------------------------------------------------------ lookup
    def get(self, profile_id: str | None) -> ModelProfile:
        pid = profile_id or self.default_id
        profile = self._profiles.get(pid)
        if profile is None:
            raise LLMConfigError(f"unknown model profile {pid!r}")
        return profile

    def ids(self) -> list[str]:
        return list(self._profiles)

    @staticmethod
    def _api_key_configured(profile: ModelProfile) -> bool:
        if not profile.api_key_env:
            return True
        if os.environ.get(profile.api_key_env):
            return True
        # Accept the conventional GitHub token name as an alternative for GitHub Models.
        return profile.api_key_env == "GITHUB_MODELS_TOKEN" and bool(os.environ.get("GITHUB_TOKEN"))

    def disabled_reason(self, profile: ModelProfile) -> str | None:
        if not profile.model:
            return "no model id configured"
        if profile.provider == "openai_compatible" and not profile.base_url:
            return "no base_url configured"
        if profile.api_key_env and not self._api_key_configured(profile):
            alternate = " or GITHUB_TOKEN" if profile.api_key_env == "GITHUB_MODELS_TOKEN" else ""
            return f"set {profile.api_key_env}{alternate} to enable"
        if profile.provider == "anthropic" and importlib.util.find_spec("anthropic") is None:
            return "install the 'anthropic' extra (pip install -e .[anthropic])"
        return None

    def require_enabled(self, profile_id: str | None) -> ModelProfile:
        profile = self.get(profile_id)
        reason = self.disabled_reason(profile)
        if reason:
            raise LLMConfigError(f"model profile {profile.id!r} is disabled: {reason}")
        return profile

    def statuses(self) -> list[ProfileStatus]:
        out: list[ProfileStatus] = []
        for p in self._profiles.values():
            reason = self.disabled_reason(p)
            out.append(ProfileStatus(id=p.id, label=p.label, provider=p.provider, model=p.model, local=p.local,
                                     description=p.description, enabled=reason is None, disabled_reason=reason,
                                     is_default=p.id == self.default_id, pricing=p.pricing,
                                     context_tokens=p.context_tokens))
        return out
