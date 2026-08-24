from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

from app.vnext.llm.protocol import ModelRequest, ModelResponse, ModelTextDelta


class ScriptedModelClient:
    """A deterministic model fake that records every complete request."""

    def __init__(self, responses: Sequence[ModelResponse | Exception | Awaitable[Any]]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("scripted model ran out of responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if inspect.isawaitable(response):
            response = await response
        return response


class ScriptedTranscriptModelClient:
    """A deterministic model script whose next turn can inspect the transcript."""

    def __init__(
        self,
        responders: Sequence[Callable[[ModelRequest], ModelResponse]],
    ) -> None:
        self.responders = list(responders)
        self.requests: list[ModelRequest] = []
        self.responses: list[ModelResponse] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self.responders:
            raise AssertionError("scripted transcript model ran out of responses")
        response = self.responders.pop(0)(request)
        self.responses.append(response)
        return response


class ScriptedStreamingModelClient:
    """A deterministic model fake that emits typed streaming items per request."""

    def __init__(
        self,
        streams: Sequence[
            Sequence[ModelTextDelta | ModelResponse | Exception | Awaitable[Any]]
        ],
    ) -> None:
        self.streams = [list(stream) for stream in streams]
        self.requests: list[ModelRequest] = []

    def stream(
        self,
        request: ModelRequest,
    ) -> AsyncIterator[ModelTextDelta | ModelResponse]:
        self.requests.append(request)
        if not self.streams:
            raise AssertionError("scripted streaming model ran out of streams")
        items = self.streams.pop(0)

        async def emit() -> AsyncIterator[ModelTextDelta | ModelResponse]:
            for item in items:
                if isinstance(item, Exception):
                    raise item
                if inspect.isawaitable(item):
                    item = await item
                if not isinstance(item, (ModelTextDelta, ModelResponse)):
                    raise AssertionError("scripted stream item has an invalid type")
                yield item

        return emit()
