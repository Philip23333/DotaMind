from app.agentic.planning.controller import AgentController
from app.agentic.tools import build_default_tool_registry
from app.core.config import Settings


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
