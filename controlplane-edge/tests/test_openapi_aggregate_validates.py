"""Merged /v1/openapi.json validates as OpenAPI 3.x and includes upstream path prefixes."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openapi_spec_validator import validate

from controlplane_edge.aggregation import register_aggregation_routes
from controlplane_edge.openapi_aggregate import build_merged_openapi_for_version
from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings


@pytest.fixture
def minimal_app():
    app = FastAPI(title="Val", version="1.0.0")

    @app.get("/gw-only")
    def _g():
        return {"x": 1}

    return app


def _stub_openapi(paths: dict) -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "S", "version": "1"},
        "paths": paths,
        "components": {"schemas": {}},
    }


@pytest.mark.asyncio
async def test_merged_openapi_passes_openapi_spec_validator(minimal_app, monkeypatch):
    monkeypatch.setenv("CPEDGE_AUTH_SERVICE_URL", "http://auth.v.test")
    monkeypatch.setenv("CPEDGE_USER_SERVICE_URL", "http://user.v.test")
    settings = OpenAPIAggregationSettings()
    auth_doc = _stub_openapi({"/auth/x": {"get": {"responses": {"200": {"description": "ok"}}}}})
    user_doc = _stub_openapi({"/api/v1/users": {"get": {"responses": {"200": {"description": "ok"}}}}})
    with respx.mock:
        respx.get("http://auth.v.test/openapi.json").mock(return_value=httpx.Response(200, json=auth_doc))
        respx.get("http://user.v.test/openapi.json").mock(return_value=httpx.Response(200, json=user_doc))
        merged = await build_merged_openapi_for_version(minimal_app, settings, version_label="v1")
    validate(merged)
    paths = merged["paths"]
    assert "/gw-only" in paths or any("gw-only" in k for k in paths)
    assert "/_upstream/auth/auth/x" in paths
    assert "/_upstream/user/api/v1/users" in paths
    src = merged.get("x-controlplane-edge-meta", {}).get("sources", [])
    assert "controlplane-edge" in src and "auth" in src and "user" in src


def test_v1_openapi_json_endpoint_validates_with_testclient(minimal_app, monkeypatch):
    monkeypatch.setenv("CPEDGE_AUTH_SERVICE_URL", "http://auth.tc.test")
    register_aggregation_routes(minimal_app)
    doc = _stub_openapi({"/auth/me": {"get": {"responses": {"200": {"description": "ok"}}}}})
    with respx.mock:
        respx.get("http://auth.tc.test/openapi.json").mock(return_value=httpx.Response(200, json=doc))
        with TestClient(minimal_app) as client:
            r = client.get("/v1/openapi.json")
    assert r.status_code == 200
    validate(r.json())


@pytest.mark.asyncio
async def test_merged_openapi_includes_all_upstream_prefixes(minimal_app, monkeypatch):
    """Checklist: one path key per merged service id (see openapi_merge path_prefix)."""
    bases = {
        "CPEDGE_AUTH_SERVICE_URL": "http://auth.chk",
        "CPEDGE_USER_SERVICE_URL": "http://user.chk",
        "CPEDGE_PAYMENT_SERVICE_URL": "http://pay.chk",
        "CPEDGE_ACL_SERVICE_URL": "http://acl.chk",
        "CPEDGE_MARKETPLACE_SERVICE_URL": "http://mkt.chk",
        "CPEDGE_AI_SERVICE_URL": "http://ai.chk",
    }
    for k, v in bases.items():
        monkeypatch.setenv(k, v)
    settings = OpenAPIAggregationSettings()
    stubs = {
        "auth": _stub_openapi({"/a": {"get": {"responses": {"200": {"description": "ok"}}}}}),
        "user": _stub_openapi({"/u": {"get": {"responses": {"200": {"description": "ok"}}}}}),
        "payment": _stub_openapi({"/p": {"get": {"responses": {"200": {"description": "ok"}}}}}),
        "acl": _stub_openapi({"/c": {"get": {"responses": {"200": {"description": "ok"}}}}}),
        "marketplace": _stub_openapi({"/m": {"get": {"responses": {"200": {"description": "ok"}}}}}),
        "ai": _stub_openapi({"/i": {"get": {"responses": {"200": {"description": "ok"}}}}}),
    }
    with respx.mock:
        respx.get("http://auth.chk/openapi.json").mock(return_value=httpx.Response(200, json=stubs["auth"]))
        respx.get("http://user.chk/openapi.json").mock(return_value=httpx.Response(200, json=stubs["user"]))
        respx.get("http://pay.chk/openapi.json").mock(return_value=httpx.Response(200, json=stubs["payment"]))
        respx.get("http://acl.chk/openapi.json").mock(return_value=httpx.Response(200, json=stubs["acl"]))
        respx.get("http://mkt.chk/openapi.json").mock(return_value=httpx.Response(200, json=stubs["marketplace"]))
        respx.get("http://ai.chk/openapi.json").mock(return_value=httpx.Response(200, json=stubs["ai"]))
        merged = await build_merged_openapi_for_version(minimal_app, settings, version_label="v1")
    validate(merged)
    p = merged["paths"]
    assert "/_upstream/auth/a" in p
    assert "/_upstream/user/u" in p
    assert "/_upstream/payment/p" in p
    assert "/_upstream/acl/c" in p
    assert "/_upstream/marketplace/m" in p
    assert "/_upstream/ai/i" in p
    assert merged.get("x-controlplane-edge-meta", {}).get("sources") == [
        "controlplane-edge",
        "auth",
        "user",
        "payment",
        "acl",
        "marketplace",
        "ai",
    ]


@pytest.mark.asyncio
async def test_merged_openapi_includes_template_upstream(minimal_app, monkeypatch):
    monkeypatch.setenv("CPEDGE_TEMPLATE_SERVICE_URL", "http://tpl.chk")
    settings = OpenAPIAggregationSettings()
    doc = _stub_openapi(
        {"/api/v1/samples": {"get": {"responses": {"200": {"description": "ok"}}}}}
    )
    with respx.mock:
        respx.get("http://tpl.chk/openapi.json").mock(
            return_value=httpx.Response(200, json=doc)
        )
        merged = await build_merged_openapi_for_version(
            minimal_app, settings, version_label="v1"
        )
    validate(merged)
    assert "/_upstream/template/api/v1/samples" in merged["paths"]
    assert "template" in merged.get("x-controlplane-edge-meta", {}).get("sources", [])


@pytest.mark.asyncio
async def test_merged_openapi_includes_tennessee_windage_upstream(minimal_app, monkeypatch):
    monkeypatch.setenv("CPEDGE_TENNESSEE_WINDAGE_SERVICE_URL", "http://tw.chk")
    settings = OpenAPIAggregationSettings()
    doc = _stub_openapi(
        {"/api/v1/tw/missions": {"get": {"responses": {"200": {"description": "ok"}}}}}
    )
    with respx.mock:
        respx.get("http://tw.chk/openapi.json").mock(
            return_value=httpx.Response(200, json=doc)
        )
        merged = await build_merged_openapi_for_version(
            minimal_app, settings, version_label="v1"
        )
    validate(merged)
    assert "/_upstream/tennessee_windage/api/v1/tw/missions" in merged["paths"]
    assert "tennessee_windage" in merged.get("x-controlplane-edge-meta", {}).get("sources", [])


@pytest.mark.asyncio
async def test_merged_openapi_includes_hypermesh_upstream(minimal_app, monkeypatch):
    monkeypatch.setenv("CPEDGE_HYPERMESH_SERVICE_URL", "http://hm.chk")
    settings = OpenAPIAggregationSettings()
    doc = _stub_openapi(
        {"/api/v1/hypermesh/leases": {"get": {"responses": {"200": {"description": "ok"}}}}}
    )
    with respx.mock:
        respx.get("http://hm.chk/openapi.json").mock(
            return_value=httpx.Response(200, json=doc)
        )
        merged = await build_merged_openapi_for_version(
            minimal_app, settings, version_label="v1"
        )
    validate(merged)
    assert "/_upstream/hypermesh/api/v1/hypermesh/leases" in merged["paths"]
    assert "hypermesh" in merged.get("x-controlplane-edge-meta", {}).get("sources", [])


@pytest.mark.asyncio
async def test_merged_openapi_includes_aiuditor_upstream(minimal_app, monkeypatch):
    monkeypatch.setenv("CPEDGE_AIUDITOR_SERVICE_URL", "http://aiuditor.chk")
    settings = OpenAPIAggregationSettings()
    doc = _stub_openapi(
        {
            "/api/v1/aiuditor/connections": {
                "get": {"responses": {"200": {"description": "ok"}}}
            }
        }
    )
    with respx.mock:
        respx.get("http://aiuditor.chk/openapi.json").mock(
            return_value=httpx.Response(200, json=doc)
        )
        merged = await build_merged_openapi_for_version(
            minimal_app, settings, version_label="v1"
        )
    validate(merged)
    assert "/_upstream/aiuditor/api/v1/aiuditor/connections" in merged["paths"]
    assert "aiuditor" in merged.get("x-controlplane-edge-meta", {}).get("sources", [])


@pytest.mark.asyncio
async def test_merged_openapi_includes_turn_upstream(minimal_app, monkeypatch):
    monkeypatch.setenv("CPEDGE_TURN_SERVICE_URL", "http://turn.chk")
    settings = OpenAPIAggregationSettings()
    doc = _stub_openapi(
        {"/api/v1/turn/allocate": {"post": {"responses": {"200": {"description": "ok"}}}}}
    )
    with respx.mock:
        respx.get("http://turn.chk/openapi.json").mock(
            return_value=httpx.Response(200, json=doc)
        )
        merged = await build_merged_openapi_for_version(
            minimal_app, settings, version_label="v1"
        )
    validate(merged)
    assert "/_upstream/turn/api/v1/turn/allocate" in merged["paths"]
    assert "turn" in merged.get("x-controlplane-edge-meta", {}).get("sources", [])


@pytest.mark.asyncio
async def test_merged_openapi_includes_oracles_upstream(minimal_app, monkeypatch):
    monkeypatch.setenv("CPEDGE_ORACLES_SERVICE_URL", "http://oracles.chk")
    settings = OpenAPIAggregationSettings()
    doc = _stub_openapi(
        {"/api/v1/oracles/v0/attest": {"post": {"responses": {"200": {"description": "ok"}}}}}
    )
    with respx.mock:
        respx.get("http://oracles.chk/openapi.json").mock(
            return_value=httpx.Response(200, json=doc)
        )
        merged = await build_merged_openapi_for_version(
            minimal_app, settings, version_label="v1"
        )
    validate(merged)
    assert "/_upstream/oracles/api/v1/oracles/v0/attest" in merged["paths"]
    assert "oracles" in merged.get("x-controlplane-edge-meta", {}).get("sources", [])


@pytest.mark.asyncio
async def test_merged_openapi_includes_payments_upstream(minimal_app, monkeypatch):
    monkeypatch.setenv("CPEDGE_PAYMENTS_SERVICE_URL", "http://payments.chk")
    settings = OpenAPIAggregationSettings()
    doc = _stub_openapi(
        {
            "/api/v1/payments/v0/intent": {
                "post": {"responses": {"200": {"description": "ok"}}}
            },
            "/api/v1/payments/v0/receipt": {
                "post": {"responses": {"200": {"description": "ok"}}}
            },
        }
    )
    with respx.mock:
        respx.get("http://payments.chk/openapi.json").mock(
            return_value=httpx.Response(200, json=doc)
        )
        merged = await build_merged_openapi_for_version(
            minimal_app, settings, version_label="v1"
        )
    validate(merged)
    assert "/_upstream/payments/api/v1/payments/v0/intent" in merged["paths"]
    assert "/_upstream/payments/api/v1/payments/v0/receipt" in merged["paths"]
    assert "payments" in merged.get("x-controlplane-edge-meta", {}).get("sources", [])


@pytest.mark.asyncio
async def test_merged_openapi_lists_live_public_hypermesh_browse(minimal_app):
    from controlplane_edge.public_hypermesh_browse import router as browse_router

    minimal_app.include_router(browse_router)
    settings = OpenAPIAggregationSettings()
    merged = await build_merged_openapi_for_version(
        minimal_app, settings, version_label="v1"
    )
    validate(merged)
    assert "/api/v1/hypermesh/catalog" in merged["paths"]
    assert "/api/v1/hypermesh/classes" in merged["paths"]
    assert "get" in merged["paths"]["/api/v1/hypermesh/catalog"]
    assert "get" in merged["paths"]["/api/v1/hypermesh/classes"]
