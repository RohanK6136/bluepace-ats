"""Versioned prompt templates: Markdown files with YAML front-matter and `## system` / `## user` Jinja2 sections.

Each feature owns a `PromptLibrary` pointed at its own prompts directory, so prompt text never lives in Python
and every template carries a `version` that is part of the LLM cache key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

_env = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=False)
_SECTION_RE = re.compile(r"^## (system|user)\s*$", re.M)


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    step: str
    version: int
    system_src: str
    user_src: str

    def render(self, **variables: Any) -> tuple[str, str]:
        system = _env.from_string(self.system_src).render(**variables).strip()
        user = _env.from_string(self.user_src).render(**variables).strip()
        return system, user


def parse_prompt(name: str, text: str) -> PromptTemplate:
    if not text.startswith("---"):
        raise ValueError(f"prompt {name}: missing front-matter")
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front) or {}
    parts = _SECTION_RE.split(body)
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    if "system" not in sections or "user" not in sections:
        raise ValueError(f"prompt {name}: needs '## system' and '## user'")
    return PromptTemplate(name=name, step=str(meta.get("step", name)), version=int(meta["version"]),
                          system_src=sections["system"].strip(), user_src=sections["user"].strip())


class PromptLibrary:
    """Loads templates (`<name>.md`), exemplars (`exemplars/<name>.md`) and YAML snippets from one directory."""

    def __init__(self, prompt_dir: Path, exemplar_dir: Path | None = None):
        self.prompt_dir = prompt_dir
        self.exemplar_dir = exemplar_dir or prompt_dir

    @cache  # noqa: B019 - libraries are module-level singletons; the cache lives as long as the process
    def load(self, name: str) -> PromptTemplate:
        return parse_prompt(name, (self.prompt_dir / f"{name}.md").read_text(encoding="utf-8"))

    @cache  # noqa: B019
    def exemplar(self, name: str) -> str:
        return (self.exemplar_dir / f"{name}.md").read_text(encoding="utf-8").strip()

    @cache  # noqa: B019
    def yaml(self, name: str) -> dict[str, Any]:
        return yaml.safe_load((self.prompt_dir / f"{name}.yaml").read_text(encoding="utf-8"))

    def versions(self) -> dict[str, int]:
        return {p.stem: self.load(p.stem).version for p in sorted(self.prompt_dir.glob("*.md"))}
