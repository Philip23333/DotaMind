from fastapi.testclient import TestClient

from app.main import app


def test_query_console_is_served_by_api() -> None:
    response = TestClient(app).get("/debug/chat")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "MetaMind Query Lab" in response.text
    assert 'fetch("/api/v1/query"' in response.text
    assert "team_selection" in response.text
    assert "查询这个战队" in response.text
