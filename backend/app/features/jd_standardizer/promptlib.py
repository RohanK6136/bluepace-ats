"""The JD Standardizer's prompt library (templates in ./prompts, style exemplars in ./exemplars)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.llm.prompt_loader import PromptLibrary, PromptTemplate

FEATURE_DIR = Path(__file__).resolve().parent
LIBRARY = PromptLibrary(FEATURE_DIR / "prompts", FEATURE_DIR / "exemplars")


def load_prompt(name: str) -> PromptTemplate:
    return LIBRARY.load(name)


def load_exemplar(section: str) -> str:
    return LIBRARY.exemplar(section)


def load_styles() -> dict[str, Any]:
    return LIBRARY.yaml("styles")


def prompt_versions() -> dict[str, int]:
    return LIBRARY.versions()
