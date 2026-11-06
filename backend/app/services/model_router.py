"""Task-based model routing for BluePace ATS.

OpenRouter is deliberately free-only in this deployment. Environment variables
from older deployments are sanitized at startup so a stale paid model selection
cannot silently reintroduce credit-consuming requests.
"""

import os


FREE_OPENROUTER_MODEL = "openrouter/free"


def free_openrouter_model(value: str | None) -> str:
    """Return an OpenRouter model only when it is explicitly free.

    The Free Models Router is preferred because its pool is maintained by
    OpenRouter. Explicit :free variants are also safe. All other IDs, including
    legacy paid model overrides, fall back to the free router.
    """
    candidate = str(value or "").strip()
    if candidate == FREE_OPENROUTER_MODEL or candidate.lower().endswith(":free"):
        return candidate
    return FREE_OPENROUTER_MODEL


DEFAULT_MODEL = free_openrouter_model(os.getenv("OPENROUTER_MODEL"))
ASSISTANT_MODEL = free_openrouter_model(os.getenv("OPENROUTER_ASSISTANT_MODEL") or DEFAULT_MODEL)
VALIDATION_MODEL = free_openrouter_model(os.getenv("OPENROUTER_VALIDATION_MODEL") or DEFAULT_MODEL)
MATCHING_MODEL = free_openrouter_model(os.getenv("MATCHING_CHAT_MODEL") or DEFAULT_MODEL)
DEEP_REASONING_MODEL = free_openrouter_model(os.getenv("OPENROUTER_DEEP_REASONING_MODEL") or DEFAULT_MODEL)

# Embeddings remain a separate provider concern; they are not sent through the
# OpenRouter chat-completion model router.
EMBEDDING_MODEL = os.getenv("MATCHING_EMBEDDING_MODEL", "text-embedding-3-small")
PROMPT_VERSION = os.getenv("AI_PROMPT_VERSION", "2026-11-06.1")


def model_for(task: str, *, deep: bool = False) -> str:
    """Return the free-only configured model for an ATS task."""
    if deep or task == "deep_reasoning":
        return DEEP_REASONING_MODEL
    mapping = {
        "assistant": ASSISTANT_MODEL,
        "validation": VALIDATION_MODEL,
        "matching_summary": MATCHING_MODEL,
        "default": DEFAULT_MODEL,
    }
    return mapping.get(task, DEFAULT_MODEL)
