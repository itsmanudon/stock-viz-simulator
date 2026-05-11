from fastapi.testclient import TestClient

from stockviz.main import app

client = TestClient(app)


def test_health_returns_version() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["version"]
    assert body["status"] in ("ok", "degraded")
    assert body["database"] in ("up", "down")
