from __future__ import annotations

import asyncio

import pytest

from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.llm.protocol import ModelResponse, UserMessage
from app.vnext.providers.source_reads import read_source, source_read_scope
from app.vnext.tools import ToolRegistry


def test_cache_preserves_empty_values_isolates_mutation_and_owner() -> None:
    async def scenario():
        owner = object()
        calls = 0

        async def fetch():
            nonlocal calls
            calls += 1
            return {"items": []}

        with source_read_scope() as cache:
            first = await read_source(owner, "rows", 1, fetch)
            first["items"].append("changed")
            assert await read_source(owner, "rows", 1, fetch) == {"items": []}
            await read_source(object(), "rows", 1, fetch)
            assert (calls, cache.remote_reads, cache.cache_hits) == (2, 2, 1)
        assert cache._values == {}
        with source_read_scope():
            assert await read_source(owner, "rows", 1, fetch) == {"items": []}
        assert calls == 3

    asyncio.run(scenario())


@pytest.mark.parametrize("value", [[], None])
def test_successful_empty_reads_are_reused(value) -> None:
    async def scenario():
        owner = object()

        async def fetch():
            return value

        with source_read_scope() as cache:
            assert await read_source(owner, "rows", None, fetch) == value
            assert await read_source(owner, "rows", None, fetch) == value
            assert (cache.remote_reads, cache.cache_hits) == (1, 1)

    asyncio.run(scenario())


def test_errors_and_cancelled_reads_are_not_cached() -> None:
    async def scenario():
        owner = object()
        entered = asyncio.Event()

        async def fail():
            raise ValueError("source failed")

        async def wait():
            entered.set()
            await asyncio.Event().wait()

        async def success():
            return [1]

        with source_read_scope() as cache:
            for _ in range(2):
                with pytest.raises(ValueError, match="source failed"):
                    await read_source(owner, "rows", 1, fail)
            pending = asyncio.create_task(read_source(owner, "rows", 1, wait))
            await entered.wait()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert await read_source(owner, "rows", 1, success) == [1]
            assert cache.remote_reads == 4

    asyncio.run(scenario())


def test_concurrent_identical_reads_share_one_validated_value() -> None:
    async def scenario():
        owner = object()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def fetch():
            entered.set()
            await release.wait()
            return [1]

        with source_read_scope() as cache:
            first = asyncio.create_task(read_source(owner, "rows", 1, fetch))
            await entered.wait()
            second = asyncio.create_task(read_source(owner, "rows", 1, fetch))
            release.set()
            values = await asyncio.gather(first, second)
            assert values == [[1], [1]]
            assert values[0] is not values[1]
            assert (cache.remote_reads, cache.cache_hits) == (1, 1)

    asyncio.run(scenario())


def test_concurrent_request_scopes_do_not_share_snapshots() -> None:
    async def scenario():
        owner = object()
        both_started = asyncio.Event()
        started = 0

        async def run_request(value):
            async def fetch():
                nonlocal started
                started += 1
                if started == 2:
                    both_started.set()
                await both_started.wait()
                return value

            with source_read_scope() as cache:
                first = await read_source(owner, "rows", 1, fetch)
                second = await read_source(owner, "rows", 1, fetch)
                assert first == second == value
                assert (cache.remote_reads, cache.cache_hits) == (1, 1)

        await asyncio.wait_for(asyncio.gather(run_request("A"), run_request("B")), 2)

    asyncio.run(scenario())


def test_runtime_scope_spans_both_stages_and_resets_each_run() -> None:
    async def scenario():
        owner = object()
        scopes = []

        async def fetch():
            return {"source": "same"}

        class Model:
            async def complete(self, request):
                assert await read_source(owner, "rows", 1, fetch) == {"source": "same"}
                return ModelResponse.from_final("done")

        def scope():
            from contextlib import contextmanager

            @contextmanager
            def enter():
                with source_read_scope() as cache:
                    scopes.append(cache)
                    yield

            return enter()

        runtime = AgentRuntime(
            Model(),
            ToolRegistry(),
            request_scope=scope,
            limits=AgentLimits(application_max_output_tokens=4096),
        )
        for _ in range(2):
            await runtime.run([UserMessage(content="test")])
        assert len(scopes) == 2
        assert all((c.remote_reads, c.cache_hits) == (1, 1) for c in scopes)
        stream = runtime.run_stream([UserMessage(content="close early")])
        await anext(stream)
        await stream.aclose()
        assert scopes[-1]._values == {}
        await read_source(owner, "rows", 1, fetch)
        assert scopes[-1].remote_reads == 0

    asyncio.run(scenario())
