"""Edge health must fail when the configured hypermesh catalog is down."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.interfaces.api_controllers.health_endpoint import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_health_ok_without_hypermesh_url(monkeypatch) -> None:
    monkeypatch.delenv("CPEDGE_HYPERMESH_SERVICE_URL", raising=False)
    response = _client().get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json()["status"] == "Ok"


def test_health_ok_when_hypermesh_url_is_blank(monkeypatch) -> None:
    monkeypatch.setenv("CPEDGE_HYPERMESH_SERVICE_URL", "  ")
    response = _client().get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json()["status"] == "Ok"


def test_health_503_when_catalog_probe_fails(monkeypatch) -> None:
    monkeypatch.setenv("CPEDGE_HYPERMESH_SERVICE_URL", "http://hypermesh-service:8000")
    with patch(
        "urllib.request.urlopen",
        side_effect=OSError("connection refused"),
    ):
        response = _client().get("/api/v1/health/")
    assert response.status_code == 503
    assert response.json()["status"] == "hypermesh unreachable"


def test_health_ok_when_catalog_returns_200(monkeypatch) -> None:
    monkeypatch.setenv("CPEDGE_HYPERMESH_SERVICE_URL", "http://hypermesh-service:8000")
    body = MagicMock()
    body.status = 200
    body.__enter__.return_value = body
    body.__exit__.return_value = False
    with patch("urllib.request.urlopen", return_value=body):
        response = _client().get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json()["status"] == "Ok"
