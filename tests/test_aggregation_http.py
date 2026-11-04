"""HTTP aggregation: merged /v1/openapi.json includes upstream paths (respx)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from controlplane_edge.aggregation import register_aggregation_routes
from controlplane_edge.openapi_aggregate import build_merged_openapi_for_version
from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings


@pytest.fixture
def minimal_app():
    app = FastAPI(title="Unit", version="9.9.9")

    @app.get("/internal/ping")
    def _ping():
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_build_merged_includes_monolith_paths(minimal_app):
    settings = OpenAPIAggregationSettings()
    merged = await build_merged_openapi_for_version(minimal_app, settings, version_label="v1")
    assert "/internal/ping" in merged["paths"]
    assert merged["x-controlplane-edge-meta"]["sources"] == ["controlplane-edge"]


@pytest.mark.asyncio
@respx.mock
async def test_build_merged_fetches_auth_openapi(minimal_app, monkeypatch):
    monkeypatch.setenv("CPEDGE_AUTH_SERVICE_URL", "http://auth.test")
    settings = OpenAPIAggregationSettings()
    auth_doc = {
        "openapi": "3.0.0",
        "info": {"title": "Auth", "version": "1"},
        "paths": {"/auth/x": {"get": {"responses": {"200": {"description": "ok"}}}}},
        "components": {"schemas": {"Token": {"type": "string"}}},
    }
    respx.get("http://auth.test/openapi.json").mock(return_value=httpx.Response(200, json=auth_doc))

    merged = await build_merged_openapi_for_version(minimal_app, settings, version_label="v1")
    assert "/_upstream/auth/auth/x" in merged["paths"]
    assert "auth__Token" in merged["components"]["schemas"]
    assert "controlplane-edge" in merged["x-controlplane-edge-meta"]["sources"]
    assert "auth" in merged["x-controlplane-edge-meta"]["sources"]


def test_v1_openapi_json_route(monkeypatch, minimal_app):
    monkeypatch.setenv("CPEDGE_AUTH_SERVICE_URL", "http://auth.route.test")
    register_aggregation_routes(minimal_app)

    auth_doc = {
        "openapi": "3.0.0",
        "info": {"title": "Auth", "version": "1"},
        "paths": {"/auth/me": {"get": {"responses": {"200": {"description": "ok"}}}}},
        "components": {"schemas": {}},
    }
    with respx.mock:
        respx.get("http://auth.route.test/openapi.json").mock(
            return_value=httpx.Response(200, json=auth_doc)
        )
        with TestClient(minimal_app) as client:
            r = client.get("/v1/openapi.json")
    assert r.status_code == 200
    data = r.json()
    assert "/_upstream/auth/auth/me" in data["paths"]


def test_changelog_openapi_route(minimal_app):
    register_aggregation_routes(minimal_app)
    with TestClient(minimal_app) as client:
        r = client.get("/changelog/openapi", params={"from": "v1", "to": "v2"})
    assert r.status_code == 200
    body = r.json()
    assert "paths_added" in body
    assert "schemas_added" in body
