"""Default model-visible vNext tool surface contracts."""

from app.vnext.composition import VNextSettings, build_vnext_registry


def test_default_registry_hides_transitional_tools() -> None:
    registry = build_vnext_registry(settings=VNextSettings())

    assert {tool.name for tool in registry.schemas()} == {
        "artifact.grep",
        "artifact.read",
        "artifact.search",
        "esports.search",
        "game.detail",
    }
