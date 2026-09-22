from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from app.vnext.agent.errors import ModelContextWindowExceeded
from app.vnext.agent.runtime import AgentRuntime, CancellationToken, _Deadline
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm import ModelContextWindowError
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient, ProviderHTTPError
from app.vnext.llm.protocol import (
    FinalMessage,
    ModelRequest,
    ModelResponse,
    ModelTextDelta,
    UserMessage,
)
from app.vnext.tools.registry import ToolRegistry

_SENSITIVE_BODY = "provider-secret-context-details"


def _request() -> ModelRequest:
    return ModelRequest(messages=[UserMessage(content="hello")])


def _run(awaitable: Awaitable[Any]) -> Any:
    return asyncio.run(asyncio.wait_for(awaitable, timeout=1))


def _adapter(handler: Callable[[httpx.Request], httpx.Response]) -> OpenAICompatibleModelClient:
    return OpenAICompatibleModelClient(
        api_key="test-key",
        base_url="https://provider.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )


def _context_error_payload() -> dict[str, Any]:
    return {
        "error": {
            "code": "context_length_exceeded",
            "message": _SENSITIVE_BODY,
        }
    }


def _sse(*chunks: object) -> str:
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
    return "".join(lines) + "data: [DONE]\n\n"


def test_http_context_error_is_classified_for_supported_statuses() -> None:
    for status_code in (400, 413, 422):
        calls = 0

        def handler(request: httpx.Request, status_code: int = status_code) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                status_code,
                json=_context_error_payload(),
                request=request,
            )

        with pytest.raises(ModelContextWindowError) as raised:
            _run(_adapter(handler).complete(_request()))

        assert calls == 1
        assert raised.value.provider_code == "context_length_exceeded"
        assert raised.value.status_code == status_code
        assert str(raised.value) == "model provider reported a context window limit"
        assert _SENSITIVE_BODY not in str(raised.value)


def test_stream_http_context_error_uses_the_same_classification() -> None:
    for status_code in (400, 413, 422):
        calls = 0

        def handler(request: httpx.Request, status_code: int = status_code) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                status_code,
                json=_context_error_payload(),
                request=request,
            )

        async def consume() -> None:
            async for _ in _adapter(handler).stream(_request()):
                raise AssertionError("a failed stream must not yield a response")

        with pytest.raises(ModelContextWindowError) as raised:
            _run(consume())

        assert calls == 1
        assert raised.value.status_code == status_code


@pytest.mark.parametrize(
    ("status_code", "payload"),
    [
        (400, {"error": {"code": "invalid_request_error", "message": _SENSITIVE_BODY}}),
        (413, {"error": {"message": _SENSITIVE_BODY}}),
    ],
)
def test_http_error_without_explicit_context_code_keeps_http_error(
    status_code: int,
    payload: object,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload, request=request)

    with pytest.raises(ProviderHTTPError) as raised:
        _run(_adapter(handler).complete(_request()))

    assert raised.value.status_code == status_code


@pytest.mark.parametrize("status_code", [401, 403, 429, 500])
def test_unsupported_http_status_keeps_http_error_even_with_context_code(status_code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=_context_error_payload(), request=request)

    with pytest.raises(ProviderHTTPError) as raised:
        _run(_adapter(handler).complete(_request()))

    assert raised.value.status_code == status_code


@pytest.mark.parametrize("body", ["not-json", [], {"error": {"code": 123}}])
def test_malformed_or_nonmatching_http_body_keeps_original_http_error(body: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(400, text=body, request=request)
        return httpx.Response(400, json=body, request=request)

    with pytest.raises(ProviderHTTPError) as raised:
        _run(_adapter(handler).complete(_request()))

    assert raised.value.status_code == 400


def test_success_response_error_object_is_classified_before_choices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_context_error_payload(), request=request)

    with pytest.raises(ModelContextWindowError) as raised:
        _run(_adapter(handler).complete(_request()))

    assert raised.value.status_code is None


def test_sse_error_object_stops_without_terminal_response() -> None:
    items: list[ModelTextDelta | ModelResponse] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse(_context_error_payload()),
            request=request,
        )

    async def consume() -> None:
        async for item in _adapter(handler).stream(_request()):
            items.append(item)

    with pytest.raises(ModelContextWindowError):
        _run(consume())

    assert items == []
    assert not any(isinstance(item, ModelResponse) for item in items)


def test_sse_delta_before_error_does_not_produce_successful_terminal_response() -> None:
    items: list[ModelTextDelta | ModelResponse] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse(
                {"choices": [{"delta": {"content": "partial"}, "finish_reason": None}]},
                _context_error_payload(),
            ),
            request=request,
        )

    async def consume() -> None:
        async for item in _adapter(handler).stream(_request()):
            items.append(item)

    with pytest.raises(ModelContextWindowError):
        _run(consume())

    assert [item.text for item in items if isinstance(item, ModelTextDelta)] == ["partial"]
    assert not any(isinstance(item, ModelResponse) for item in items)


@pytest.mark.parametrize(
    "content",
    [
        "context_length_exceeded is just text",
        "the provider says this is too long, but it is a normal answer",
    ],
)
def test_normal_answer_text_is_not_classified_as_context_error(content: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]},
            request=request,
        )

    response = _run(_adapter(handler).complete(_request()))
    assert response.message == FinalMessage(content=content)


def test_finish_reason_length_keeps_normal_response_semantics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "truncated"}, "finish_reason": "length"}
                ]
            },
            request=request,
        )

    response = _run(_adapter(handler).complete(_request()))
    assert response.message == FinalMessage(content="truncated")
    assert response.finish_reason == "length"


def _invoke(runtime: AgentRuntime) -> Any:
    return _run(
        runtime._invoke_model(
            _request(),
            token=CancellationToken(),
            deadline=_Deadline(1),
            step=1,
            trace_collector=AgentTraceCollector(),
            publish_text=True,
        )
    )


def test_runtime_converts_non_stream_context_error_without_retry_or_sensitive_text() -> None:
    cause = ModelContextWindowError(
        provider_code="context_length_exceeded",
        status_code=413,
    )

    class Client:
        calls = 0

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            raise cause

    client = Client()
    with pytest.raises(ModelContextWindowExceeded) as raised:
        _invoke(AgentRuntime(client, ToolRegistry()))  # type: ignore[arg-type]

    error = raised.value
    assert client.calls == 1
    assert error.code == "model_context_window_exceeded"
    assert error.cause is cause
    assert error.details == {
        "exception_type": "ModelContextWindowError",
        "provider_code": "context_length_exceeded",
        "status_code": 413,
    }
    assert _SENSITIVE_BODY not in str(error)
    assert _SENSITIVE_BODY not in str(error.cause)


def test_runtime_converts_stream_context_error_after_delta_without_success() -> None:
    cause = ModelContextWindowError(
        provider_code="context_length_exceeded",
        status_code=None,
    )

    class Client:
        calls = 0
        closed = False

        def stream(self, request: ModelRequest):
            self.calls += 1

            async def emit():
                try:
                    yield ModelTextDelta(text="partial")
                    raise cause
                finally:
                    self.closed = True

            return emit()

    client = Client()
    with pytest.raises(ModelContextWindowExceeded) as raised:
        _invoke(AgentRuntime(client, ToolRegistry()))  # type: ignore[arg-type]

    assert client.calls == 1
    assert client.closed is True
    assert raised.value.cause is cause
    assert raised.value.details == {
        "exception_type": "ModelContextWindowError",
        "provider_code": "context_length_exceeded",
        "status_code": None,
    }
    assert _SENSITIVE_BODY not in str(raised.value)
