import asyncio

import pytest

from app.llm.provider import LLMJSONDecodeError, OpenAICompatibleProvider


def test_complete_json_exposes_raw_content_on_decode_error(monkeypatch) -> None:
    client_timeouts = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {"content": '{"status":"planned","reason":"cut'},
                        "finish_reason": "length",
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout
            client_timeouts.append(timeout)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, *args, **kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("app.llm.provider.httpx.AsyncClient", FakeClient)
    provider = OpenAICompatibleProvider(
        api_key="test",
        base_url="https://api.test",
        model="test-model",
    )

    with pytest.raises(LLMJSONDecodeError) as exc_info:
        asyncio.run(
            provider.complete_json(
                [{"role": "user", "content": "return json"}],
                max_tokens=10,
            )
        )

    assert exc_info.value.raw_content == '{"status":"planned","reason":"cut'
    assert exc_info.value.finish_reason == "length"
    assert client_timeouts == [90.0]


def test_stream_complete_forwards_only_sse_content_deltas(monkeypatch) -> None:
    stream_requests = []

    class FakeResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def aiter_lines(self):
            for line in (
                "",
                "event: message",
                'data: {"choices":[{"delta":{"content":"首"}}]}',
                'data: {"choices":[{"delta":{"content":"个"}}]}',
                'data: {"choices":[{"delta":{}}]}',
                "data: [DONE]",
                'data: {"choices":[{"delta":{"content":"忽略"}}]}',
            ):
                yield line

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        def stream(self, *args, **kwargs) -> FakeResponse:
            stream_requests.append((args, kwargs))
            return FakeResponse()

    async def collect(provider: OpenAICompatibleProvider) -> list[str]:
        return [
            delta
            async for delta in provider.stream_complete(
                [{"role": "user", "content": "stream"}],
                max_tokens=10,
            )
        ]

    monkeypatch.setattr("app.llm.provider.httpx.AsyncClient", FakeClient)
    provider = OpenAICompatibleProvider(
        api_key="test",
        base_url="https://api.test",
        model="test-model",
    )

    assert asyncio.run(collect(provider)) == ["首", "个"]
    assert stream_requests[0][0] == ("POST", "https://api.test/chat/completions")
    assert stream_requests[0][1]["json"]["stream"] is True


def test_stream_complete_propagates_upstream_http_errors(monkeypatch) -> None:
    class FakeResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        def raise_for_status(self) -> None:
            raise RuntimeError("upstream unavailable")

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        def stream(self, *args, **kwargs) -> FakeResponse:
            return FakeResponse()

    async def collect(provider: OpenAICompatibleProvider) -> list[str]:
        return [
            delta
            async for delta in provider.stream_complete(
                [{"role": "user", "content": "stream"}],
                max_tokens=10,
            )
        ]

    monkeypatch.setattr("app.llm.provider.httpx.AsyncClient", FakeClient)
    provider = OpenAICompatibleProvider(
        api_key="test",
        base_url="https://api.test",
        model="test-model",
    )

    with pytest.raises(RuntimeError, match="upstream unavailable"):
        asyncio.run(collect(provider))

