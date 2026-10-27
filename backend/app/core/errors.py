"""Error taxonomy. LLM errors are provider-neutral: every provider maps its own failures onto these."""


class LLMError(Exception):
    """Base class for LLM-layer failures."""

    retryable = False


class LLMUnavailable(LLMError):
    """Endpoint unreachable (connection refused, DNS, 502/503/504). The run degrades to rules-only."""


class LLMConfigError(LLMUnavailable):
    """Profile unknown, disabled or misconfigured (missing API key, SDK not installed, bad credentials)."""


class LLMTimeout(LLMError):
    retryable = True


class LLMRateLimited(LLMError):
    retryable = True


class LLMTruncated(LLMError):
    """The model hit max_tokens before finishing the JSON."""

    retryable = True


class LLMInvalidJSON(LLMError):
    retryable = True


class LLMRefusal(LLMError):
    """The model declined the request (safety classifier)."""


class LLMBadResponse(LLMError):
    """Transient server error (5xx) or a malformed body."""

    retryable = True


class LLMRejected(LLMError):
    """The provider rejected the request itself (4xx other than auth/rate limit). Retrying will not help."""


class LLMBudgetExceeded(LLMError):
    """Prompt + max_tokens does not fit the profile's context window."""


class LLMStepFailed(LLMError):
    """A step exhausted its retries; the pipeline degrades that step."""

    def __init__(self, step: str, cause: Exception):
        super().__init__(f"{step}: {type(cause).__name__}: {cause}")
        self.step = step
        self.cause = cause


class IngestError(Exception):
    """Malformed/unsupported upload → HTTP 400."""
