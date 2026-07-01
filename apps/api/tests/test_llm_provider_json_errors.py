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

