from __future__ import annotations

import asyncio
import json

import httpx

from app.llm.providers.ollama import OllamaNativeProvider
from app.llm.types import ModelProfile, ProviderRequest


def _profile() -> ModelProfile:
    return ModelProfile(
        id="local-ollama",
        label="Qwen3 8B · local",
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="qwen3:8b",
        local=True,
        structured_output="json_schema",
        context_tokens=8192,
        extra_body={"think": False, "keep_alive": "30m"},
    )


def _request() -> ProviderRequest:
    return ProviderRequest(
        step="test",
        system="Return a JSON object.",
        user="Return { ok: true }.",
        schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        max_tokens=24,
    )


def test_native_ollama_request_disables_thinking_and_keeps_model_loaded() -> None:
    provider = OllamaNativeProvider(_profile(), "Return valid JSON.")
    body = provider.build_body(_request(), stream=False)

    assert body["think"] is False
    assert body["keep_alive"] == "30m"
    assert body["format"] == _request().schema
    assert body["options"]["num_predict"] == 24
    assert body["options"]["num_ctx"] == 8192
    assert body["stream"] is False


def test_native_ollama_complete_maps_content_and_token_usage() -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": "qwen3:8b",
                "message": {"role": "assistant", "content": '{"ok": true}'},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 19,
                "eval_count": 4,
            },
        )

    async def run() -> None:
        provider = OllamaNativeProvider(_profile(), "Return valid JSON.", transport=httpx.MockTransport(handle))
        try:
            result = await provider.complete(_request())
            assert result.text == '{"ok": true}'
            assert result.finish_reason == "stop"
            assert result.usage is not None
            assert result.usage.prompt_tokens == 19
            assert result.usage.completion_tokens == 4
        finally:
            await provider.aclose()

    asyncio.run(run())
    assert seen["path"] == "/api/chat"
    assert seen["body"]["think"] is False


def test_native_ollama_stream_returns_content_and_final_usage() -> None:
    payloads = [
        {"message": {"content": '{"ok": '}, "done": False},
        {
            "message": {"content": "true}"},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 11,
            "eval_count": 3,
        },
    ]

    def handle(_request: httpx.Request) -> httpx.Response:
        content = "".join(json.dumps(item) + "\n" for item in payloads)
        return httpx.Response(200, content=content.encode("utf-8"))

    async def run() -> None:
        provider = OllamaNativeProvider(_profile(), "Return valid JSON.", transport=httpx.MockTransport(handle))
        try:
            events = [event async for event in provider.stream(_request())]
            assert events[:-1] == ['{"ok": ', "true}"]
            final = events[-1]
            assert final.finish_reason == "stop"
            assert final.usage is not None
            assert final.usage.completion_tokens == 3
        finally:
            await provider.aclose()

    asyncio.run(run())
