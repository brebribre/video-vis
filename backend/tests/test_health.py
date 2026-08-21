"""Phase 1 acceptance: `/api/health` returns ok."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_cors_allows_the_vite_origin() -> None:
    response = client.get("/api/health", headers={"Origin": "http://localhost:5175"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5175"
