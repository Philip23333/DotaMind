from __future__ import annotations

import inspect
from collections.abc import Awaitable, Sequence
from typing import Any

from app.vnext.llm.protocol import ModelRequest, ModelResponse


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
