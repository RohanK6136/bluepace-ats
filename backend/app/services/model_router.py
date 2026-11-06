"""Task-based model routing for BluePace ATS.

OpenRouter requests are deliberately restricted to free model IDs. A stale
production environment variable must never silently route a request to a paid
model when the ATS is configured for free inference.
"""

import os


def is_free_openrouter_model(value: str | None) -> bool:
    candidate = str(value or "").strip().lower()
    return candidate == "openrouter/free" or candidate.endswith(":free")


def free_model_from_env(env_name: str, fallback: str = "openrouter/free") -> str:
    """Read a model override only when it is explicitly a free OpenRouter model."""
    candidate = os.getenv(env_name, "").strip()
    return candidate if is_free_openrouter_model(candidate) else fallback


DEFAULT_MODEL = free_model_from_env("OPENROUTER_MODEL")
ASSISTANT_MODEL = free_model_from_env("OPENROUTER_ASSISTANT_MODEL", DEFAULT_MODEL)
VALIDATION_MODEL = free_model_from_env("OPENROUTER_VALIDATION_MODEL", DEFAULT_MODEL)
MATCHING_MODEL = free_model_from_env("MATCHING_CHAT_MODEL", DEFAULT_MODEL)
DEEP_REASONING_MODEL = free_model_from_env("OPENROUTER_DEEP_REASONING_MODEL", "openrouter/free")

EMBEDDING_MODEL = os.getenv("MATCHING_EMBEDDING_MODEL", "text-embedding-3-small")
PROMPT_VERSION = os.getenv("AI_PROMPT_VERSION", "2026-10-07.1")


def model_for(task: str, *, deep: bool = False) -> str:
    """Return the free-only model configured for an ATS task."""
    if deep or task == "deep_reasoning":
        return DEEP_REASONING_MODEL
    mapping = {
        "assistant": ASSISTANT_MODEL,
        "validation": VALIDATION_MODEL,
        "matching_summary": MATCHING_MODEL,
        "default": DEFAULT_MODEL,
    }
    return mapping.get(task, DEFAULT_MODEL)
