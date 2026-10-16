import asyncio

from app.agentic.planning.controller import AgentController
from app.agentic.tools import artifact_tools, build_default_tool_registry
from app.core.config import Settings
from app.vnext.artifacts import SessionArtifactStore
from app.vnext.tools.artifacts.retrieval import ArtifactGrepInput


def test_default_registry_contains_only_artifact_tools() -> None:
    registry = build_default_tool_registry(Settings(_env_file=None))
    names = {tool.name for tool in registry.list()}

    assert names == {"artifact.grep", "artifact.read"}


def test_controller_prompt_contains_only_neutral_runtime_rules() -> None:
    registry = build_default_tool_registry(Settings(_env_file=None))
    prompt = AgentController(registry, llm_enabled=False)._system_prompt()

    for tool in registry.list():
        assert tool.name in prompt
    assert "Tool Catalog:" in prompt
    assert "Output contracts:" in prompt


def test_legacy_grep_continues_from_the_advertised_offset(monkeypatch) -> None:
    store = SessionArtifactStore()
    monkeypatch.setattr(artifact_tools, "SessionArtifactStore", lambda: store)
    registry = build_default_tool_registry(Settings(_env_file=None))

    async def exercise():
        ref = await store.put({"items": [{"name": f"target-{i}"} for i in range(5)]})
        handler = registry.get("artifact.grep").handler
        return await handler(ArtifactGrepInput(ref=ref, pattern="target", limit=2, offset=2), None)

    result = asyncio.run(exercise())

    assert [match.path for match in result.matches] == ["items.2.name", "items.3.name"]
    assert result.offset == 2
    assert result.next_offset == 4
