"""Step 6: CORS, auth policy, rate limit, changelog Markdown, gRPC ContractEcho."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
import grpc.aio
import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from controlplane_edge.aggregation import register_aggregation_routes
from controlplane_edge.graphql.register import register_graphql_routes
from controlplane_edge.openapi_merge import diff_openapi_to_markdown
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting

import contractecho_pb2  # noqa: E402
import contractecho_pb2_grpc  # noqa: E402


def _fake_bearer(sub: str = "11111111-1111-1111-1111-111111111111") -> str:
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


@pytest.fixture
def cross_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("CPEDGE_AUTH_SERVICE_URL", "http://auth.cc.test")
    monkeypatch.setenv("CPEDGE_USER_SERVICE_URL", "http://user.cc.test")
    monkeypatch.setenv("CPEDGE_RATE_LIMIT_PER_MINUTE", "5000")
    app = FastAPI()
    register_gateway_cross_cutting(app)
    register_aggregation_routes(app)
    register_graphql_routes(app)
    return app


def test_v1_openapi_public_without_bearer(cross_app: FastAPI) -> None:
    respx.get("http://auth.cc.test/openapi.json").mock(return_value=httpx.Response(200, json={"openapi": "3.0.0", "paths": {}, "info": {"title": "a", "version": "1"}, "components": {"schemas": {}}}))
    with TestClient(cross_app) as client:
        r = client.get("/v1/openapi.json")
    assert r.status_code == 200


def test_graphql_post_requires_bearer(cross_app: FastAPI) -> None:
    with TestClient(cross_app) as client:
        r = client.post("/graphql", json={"query": "{ __typename }"})
    assert r.status_code == 401


def test_cors_preflight(cross_app: FastAPI) -> None:
    respx.get("http://auth.cc.test/openapi.json").mock(return_value=httpx.Response(200, json={"openapi": "3.0.0", "paths": {}, "info": {"title": "a", "version": "1"}, "components": {"schemas": {}}}))
    with TestClient(cross_app) as client:
        r = client.options(
            "/v1/openapi.json",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert r.status_code in (200, 400)


def test_rate_limit_429(cross_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    import api.core.config as api_config

    monkeypatch.setattr(api_config.settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(api_config.settings, "keycloak_issuer", None)
    from api.infrastructure.tenant_user_rate_limiter import TenantUserRateLimiter

    cross_app.state.gateway_rate_limiter = TenantUserRateLimiter(per_minute=2)
    tid = str(uuid.uuid4())
    with TestClient(cross_app) as client:
        last = None
        for _ in range(3):
            last = client.post(
                "/graphql",
                json={"query": "{ __typename }"},
                headers={"Authorization": f"Bearer {_fake_bearer()}", "X-Tenant-ID": tid},
            )
        assert last is not None
        assert last.status_code == 429


def test_changelog_markdown_renderer() -> None:
    md = diff_openapi_to_markdown(
        {
            "paths_added": ["/x"],
            "paths_removed": [],
            "schemas_added": ["Foo"],
            "schemas_removed": [],
            "info_changed": False,
        },
        title="Test",
    )
    assert "# Test" in md
    assert "/x" in md
    assert "Foo" in md


@pytest.mark.asyncio
async def test_grpc_echo_requires_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import api.core.config as api_config

    monkeypatch.setattr(api_config.settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(api_config.settings, "keycloak_issuer", None)

    from controlplane_edge.grpc_server import grpc_server_lifespan

    async with grpc_server_lifespan(host="127.0.0.1", port=0, enabled=True) as server:
        assert server is not None
        async with grpc.aio.insecure_channel(f"127.0.0.1:{server.bound_port}") as channel:
            stub = contractecho_pb2_grpc.ContractEchoStub(channel)
            req = contractecho_pb2.UserWire(id=str(uuid.uuid4()), email="a@b.com", display_name="x")
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                await stub.EchoUser(req, timeout=5.0)
            assert ei.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_grpc_echo_with_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import api.core.config as api_config

    monkeypatch.setattr(api_config.settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(api_config.settings, "keycloak_issuer", None)

    from controlplane_edge.grpc_server import grpc_server_lifespan

    tid = str(uuid.uuid4())
    async with grpc_server_lifespan(host="127.0.0.1", port=0, enabled=True) as server:
        assert server is not None
        async with grpc.aio.insecure_channel(f"127.0.0.1:{server.bound_port}") as channel:
            stub = contractecho_pb2_grpc.ContractEchoStub(channel)
            req = contractecho_pb2.UserWire(id=str(uuid.uuid4()), email="a@b.com", display_name="x")
            md = (
                ("authorization", f"Bearer {_fake_bearer()}"),
                ("x-tenant-id", tid),
            )
            out = await stub.EchoUser(req, metadata=md, timeout=5.0)
            assert out.id == req.id
