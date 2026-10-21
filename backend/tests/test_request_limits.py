import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.services.request_limits import read_request_body_limited


def make_request(chunks, headers=(), receive_calls=None):
    messages = list(chunks)
    calls = receive_calls if receive_calls is not None else []
    cursor = 0

    async def receive():
        nonlocal cursor
        calls.append(cursor)
        if cursor >= len(messages):
            return {"type": "http.request", "body": b"", "more_body": False}
        index = cursor
        cursor += 1
        return {
            "type": "http.request",
            "body": messages[index],
            "more_body": cursor < len(messages),
        }

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": "/upload",
        "raw_path": b"/upload",
        "query_string": b"",
        "headers": list(headers),
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope, receive)


def test_limited_reader_accepts_body_at_exact_limit():
    request = make_request(
        [b"12", b"345"],
        headers=[(b"content-length", b"5")],
    )
    assert asyncio.run(read_request_body_limited(request, 5)) == b"12345"


def test_limited_reader_rejects_oversize_content_length_before_reading():
    calls = []
    request = make_request(
        [b"oversized body"],
        headers=[(b"content-length", b"15")],
        receive_calls=calls,
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(read_request_body_limited(request, 5, detail="Resume must be 5 MB or smaller."))

    assert error.value.status_code == 413
    assert error.value.detail == "Resume must be 5 MB or smaller."
    assert calls == []


def test_limited_reader_stops_as_soon_as_streamed_body_exceeds_limit():
    calls = []
    request = make_request([b"1234", b"56", b"never-read"], receive_calls=calls)

    with pytest.raises(HTTPException) as error:
        asyncio.run(read_request_body_limited(request, 5))

    assert error.value.status_code == 413
    assert len(calls) == 2


def test_limited_reader_enforces_limit_when_content_length_underreports_body():
    request = make_request(
        [b"1234", b"56"],
        headers=[(b"content-length", b"2")],
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(read_request_body_limited(request, 5))

    assert error.value.status_code == 413


def test_limited_reader_rejects_invalid_content_length():
    request = make_request(
        [b"123"],
        headers=[(b"content-length", b"unknown")],
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(read_request_body_limited(request, 5))

    assert error.value.status_code == 400
