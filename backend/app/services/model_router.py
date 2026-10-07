"""Task-based model routing for BluePace ATS.

Keep model selection in one place so individual services do not silently
choose oversized or inconsistent models for routine work.
"""

import os


DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-3.8-flash")
ASSISTANT_MODEL = os.getenv("OPENROUTER_ASSISTANT_MODEL", DEFAULT_MODEL)
VALIDATION_MODEL = os.getenv("OPENROUTER_VALIDATION_MODEL", DEFAULT_MODEL)
MATCHING_MODEL = os.getenv("MATCHING_CHAT_MODEL", DEFAULT_MODEL)
DEEP_REASONING_MODEL = os.getenv("OPENROUTER_DEEP_REASONING_MODEL", "openai/gpt-5.5")

EMBEDDING_MODEL = os.getenv("MATCHING_EMBEDDING_MODEL", "text-embedding-3-small")


def model_for(task: str, *, deep: bool = False) -> str:
    """Return the configured model for an ATS task.

    The routing policy intentionally prefers a fast capable model for routine
    extraction/validation/assistant work and escalates only explicit deep
    reasoning requests.
    """
    if deep or task == "deep_reasoning":
        return DEEP_REASONING_MODEL
    mapping = {
        "assistant": ASSISTANT_MODEL,
        "validation": VALIDATION_MODEL,
        "matching_summary": MATCHING_MODEL,
        "default": DEFAULT_MODEL,
    }
    return mapping.get(task, DEFAULT_MODEL)
