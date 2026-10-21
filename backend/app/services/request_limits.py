"""Read request bodies without buffering unbounded uploads in memory."""

from __future__ import annotations

from fastapi import HTTPException, Request


async def read_request_body_limited(
    request: Request,
    max_bytes: int,
    *,
    detail: str = "Uploaded file is too large.",
) -> bytes:
    """Read at most max_bytes and reject declared or streamed overages."""
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from error
        if declared_length < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.")
        if declared_length > max_bytes:
            raise HTTPException(status_code=413, detail=detail)

    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise HTTPException(status_code=413, detail=detail)
        chunks.append(chunk)

    return b"".join(chunks)
