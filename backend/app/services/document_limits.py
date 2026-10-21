"""Shared limits for uploaded ATS documents."""

MAX_DOCUMENT_SIZE_BYTES = 5 * 1024 * 1024
MAX_DOCUMENT_SIZE_MB = 5
SUPPORTED_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx"})
