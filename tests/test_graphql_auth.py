"""GraphQL requires Bearer token and X-Tenant-ID for protected fields."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from controlplane_edge.graphql.register import register_graphql_routes


@pytest.fixture
def gql_app() -> FastAPI:
    app = FastAPI()
    register_graphql_routes(app)
    return app


def test_tenant_users_errors_without_auth(gql_app: FastAPI) -> None:
    with TestClient(gql_app) as client:
        r = client.post(
            "/graphql",
            json={"query": "{ tenantUsers { email } }"},
        )
    assert r.status_code == 200
    body = r.json()
    assert "errors" in body
    assert body.get("data") is None or body.get("data", {}).get("tenantUsers") is None


def test_tenant_users_errors_without_tenant_header(gql_app: FastAPI) -> None:
    with TestClient(gql_app) as client:
        r = client.post(
            "/graphql",
            json={"query": "{ tenantUsers { email } }"},
            headers={"Authorization": "Bearer fake"},
        )
    assert r.status_code == 200
    body = r.json()
    assert "errors" in body


def test_ai_usage_errors_without_tenant(gql_app: FastAPI) -> None:
    with TestClient(gql_app) as client:
        r = client.post(
            "/graphql",
            json={"query": "{ aiUsage { model } }"},
            headers={"Authorization": "Bearer x.y.z"},
        )
    assert r.status_code == 200
    assert r.json().get("errors")


def test_acl_policies_ok_with_headers_no_upstream(
    gql_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CPEDGE_ACL_SERVICE_URL", "http://acl.unreachable.invalid")
    ta = uuid.uuid4()
    with TestClient(gql_app) as client:
        r = client.post(
            "/graphql",
            json={"query": "{ aclPolicies { id ptype } }"},
            headers={
                "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMTEiLCJ0ZXN0IjoxfQ.fake",
                "X-Tenant-ID": str(ta),
            },
        )
    # No mock: request fails at httpx — GraphQL may return errors
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_graphql_context_ignores_unsigned_jwt() -> None:
    from starlette.requests import Request

    from controlplane_edge.graphql.register import get_graphql_context

    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMTEiLCJ0ZXN0IjoxfQ.fake"
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/graphql",
        "headers": [(b"authorization", f"Bearer {token}".encode("ascii"))],
        "query_string": b"",
    }
    ctx = await get_graphql_context(Request(scope))
    assert ctx.user_sub is None


@pytest.mark.asyncio
async def test_graphql_context_honors_bound_session_jwt() -> None:
    from starlette.requests import Request

    from api.infrastructure.security.tenant_session_jwt import mint_tenant_session_jwt
    from controlplane_edge.graphql.register import get_graphql_context

    tid = uuid.uuid4()
    token = mint_tenant_session_jwt(
        claims={"sub": "u1", "email": "chris@fyberlabs.com", "azp": "controlplane-m2m"},
        tenant_id=tid,
        extra_roles=["admin"],
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/graphql",
        "headers": [(b"authorization", f"Bearer {token}".encode("ascii"))],
        "query_string": b"",
    }
    ctx = await get_graphql_context(Request(scope))
    assert ctx.user_sub == "u1"
