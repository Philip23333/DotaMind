from fastapi.testclient import TestClient

from app.integrations.valve.catalog_repository import load_default_catalog_repository
from app.main import app


def test_dota_catalog_image_routes_serve_committed_assets() -> None:
    client = TestClient(app)

    hero = client.get("/api/v1/assets/dota/heroes/1.png")
    item = client.get("/api/v1/assets/dota/items/1.png")
    missing = client.get("/api/v1/assets/dota/heroes/999999.png")

    assert hero.status_code == 200
    assert hero.content
    assert "image/png" in hero.headers["content-type"]
    assert item.status_code == 200
    assert item.content
    assert "image/png" in item.headers["content-type"]
    assert missing.status_code == 404


def test_catalog_resolvers_return_deterministic_local_image_paths() -> None:
    repository = load_default_catalog_repository()

    hero = repository.resolve_hero("敌法师")["hero"]
    item = repository.resolve_item("闪烁匕首")["item"]

    assert hero["image_path"] == "/api/v1/assets/dota/heroes/1.png"
    assert item["image_path"] == "/api/v1/assets/dota/items/1.png"

    recipe_record = next(item for item in repository.list_items() if item.is_recipe)
    recipe = repository.resolve_item(recipe_record.name_en)["item"]
    assert recipe["image_path"] is None
