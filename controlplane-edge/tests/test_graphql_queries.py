"""GraphQL queries with respx-mocked microservices."""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.infrastructure.security.tenant_session_jwt import mint_tenant_session_jwt
from controlplane_edge.graphql.clients import page_items
from controlplane_edge.graphql.register import register_graphql_routes


def _auth_headers(tenant_id: str | uuid.UUID) -> dict[str, str]:
    tid = uuid.UUID(str(tenant_id))
    token = mint_tenant_session_jwt(
        claims={
            "sub": "11111111-1111-1111-1111-111111111111",
            "email": "renter@example.com",
        },
        tenant_id=tid,
        extra_roles=["renter"],
    )
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": str(tid)}


def _unsigned_bearer() -> str:
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "11111111-1111-1111-1111-111111111111"}).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.sig"


def test_page_items_reads_user_list_page() -> None:
    uid = str(uuid.uuid4())
    assert page_items({"items": [{"id": uid}], "total": 1, "limit": 50, "offset": 0}) == [
        {"id": uid}
    ]
    assert page_items({"total": 0, "limit": 50, "offset": 0}) == []
    assert page_items("not-a-page") == []


@pytest.fixture
def gql_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("CPEDGE_USER_SERVICE_URL", "http://user.gql.test")
    monkeypatch.setenv("CPEDGE_MARKETPLACE_SERVICE_URL", "http://mkt.gql.test")
    monkeypatch.setenv("CPEDGE_ACL_SERVICE_URL", "http://acl.gql.test")
    monkeypatch.setenv("CPEDGE_AI_SERVICE_URL", "http://ai.gql.test")
    app = FastAPI()
    register_graphql_routes(app)
    return app


@respx.mock
def test_tenant_users_returns_data(gql_app: FastAPI) -> None:
    uid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    respx.get("http://user.gql.test/api/v1/users").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": uid,
                        "tenant_id": tid,
                        "email": "a@b.com",
                        "first_name": "A",
                        "last_name": "B",
                        "gender": "unspecified",
                        "is_active": True,
                        "deleted_at": None,
                        "sociacl_attributes": None,
                        "role_id": None,
                    }
                ],
                "total": 1,
                "limit": 50,
                "offset": 0,
            },
        )
    )
    q = """
    query {
      tenantUsers { email firstName lastName }
    }
    """
    with TestClient(gql_app) as client:
        r = client.post(
            "/graphql",
            json={"query": q},
            headers=_auth_headers(tid),
        )
    assert r.status_code == 200
    body = r.json()
    assert "errors" not in body, body
    assert body["data"]["tenantUsers"][0]["email"] == "a@b.com"


@respx.mock
def test_listings_and_acl_filter(gql_app: FastAPI) -> None:
    tid = str(uuid.uuid4())
    lid = str(uuid.uuid4())
    respx.get("http://mkt.gql.test/api/v1/marketplace/listings").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": lid,
                        "tenant_id": tid,
                        "seller_id": tid,
                        "title": "t",
                        "description": "",
                        "listing_type": "agent",
                        "price_type": "free",
                        "price_amount": None,
                        "metadata": {},
                        "is_public": False,
                    }
                ],
                "total": 1,
                "limit": 50,
                "offset": 0,
            },
        )
    )
    respx.post("http://acl.gql.test/api/v1/acl/enforce").mock(
        return_value=httpx.Response(200, json={"allow": True})
    )

    q = """
    query {
      listings(applyAclFilter: true, limit: 10) { title listingType }
    }
    """
    with TestClient(gql_app) as client:
        r = client.post(
            "/graphql",
            json={"query": q},
            headers=_auth_headers(tid),
        )
    assert r.status_code == 200
    body = r.json()
    assert "errors" not in body, body
    assert body["data"]["listings"][0]["title"] == "t"


@pytest.fixture
def gql_app_no_acl(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("CPEDGE_USER_SERVICE_URL", "http://user.gql.test")
    monkeypatch.setenv("CPEDGE_MARKETPLACE_SERVICE_URL", "http://mkt.gql.test")
    monkeypatch.delenv("CPEDGE_ACL_SERVICE_URL", raising=False)
    monkeypatch.delenv("ACL_SERVICE_URL", raising=False)
    monkeypatch.setenv("CPEDGE_AI_SERVICE_URL", "http://ai.gql.test")
    app = FastAPI()
    register_graphql_routes(app)
    return app


@respx.mock
def test_missing_acl_url_filters_listings_closed(gql_app_no_acl: FastAPI) -> None:
    tid = str(uuid.uuid4())
    lid = str(uuid.uuid4())
    respx.get("http://mkt.gql.test/api/v1/marketplace/listings").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": lid,
                        "tenant_id": tid,
                        "seller_id": tid,
                        "title": "hidden",
                        "description": "",
                        "listing_type": "agent",
                        "price_type": "free",
                        "price_amount": None,
                        "metadata": {},
                        "is_public": False,
                    }
                ],
                "total": 1,
                "limit": 50,
                "offset": 0,
            },
        )
    )
    with TestClient(gql_app_no_acl) as client:
        r = client.post(
            "/graphql",
            json={"query": "{ listings(applyAclFilter: true) { title } }"},
            headers=_auth_headers(tid),
        )
    assert r.status_code == 200
    body = r.json()
    assert "errors" not in body, body
    assert body["data"]["listings"] == []
    assert not any(call.request.url.path.endswith("/acl/enforce") for call in respx.calls)


@respx.mock
def test_unsigned_jwt_does_not_pass_acl_filter(gql_app: FastAPI) -> None:
    tid = str(uuid.uuid4())
    lid = str(uuid.uuid4())
    respx.get("http://mkt.gql.test/api/v1/marketplace/listings").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": lid,
                        "tenant_id": tid,
                        "seller_id": tid,
                        "title": "hidden",
                        "description": "",
                        "listing_type": "agent",
                        "price_type": "free",
                        "price_amount": None,
                        "metadata": {},
                        "is_public": False,
                    }
                ],
                "total": 1,
                "limit": 50,
                "offset": 0,
            },
        )
    )
    respx.post("http://acl.gql.test/api/v1/acl/enforce").mock(
        return_value=httpx.Response(200, json={"allow": True})
    )
    with TestClient(gql_app) as client:
        r = client.post(
            "/graphql",
            json={"query": "{ listings(applyAclFilter: true) { title } }"},
            headers={
                "Authorization": f"Bearer {_unsigned_bearer()}",
                "X-Tenant-ID": tid,
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert "errors" not in body, body
    assert body["data"]["listings"] == []
    assert not any(
        call.request.url.path.endswith("/acl/enforce") for call in respx.calls
    )


@respx.mock
def test_acl_policies(gql_app: FastAPI) -> None:
    tid = str(uuid.uuid4())
    respx.get("http://acl.gql.test/api/v1/acl/policies").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "ptype": "p", "v0": "a", "v1": None, "v2": None, "v3": None, "v4": None, "v5": None}],
        )
    )
    q = "{ aclPolicies { id ptype v0 } }"
    with TestClient(gql_app) as client:
        r = client.post(
            "/graphql",
            json={"query": q},
            headers=_auth_headers(tid),
        )
    assert r.status_code == 200
    d = r.json()["data"]["aclPolicies"]
    assert d[0]["ptype"] == "p"


@respx.mock
def test_ai_usage_empty_page(gql_app: FastAPI) -> None:
    tid = str(uuid.uuid4())
    respx.get("http://ai.gql.test/api/v1/ai/usage/history").mock(
        return_value=httpx.Response(
            200,
            json={"items": [], "total": 0, "limit": 50, "offset": 0},
        )
    )
    q = "{ aiUsage { model } }"
    with TestClient(gql_app) as client:
        r = client.post(
            "/graphql",
            json={"query": q},
            headers=_auth_headers(tid),
        )
    assert r.status_code == 200
    body = r.json()
    assert "errors" not in body, body
    assert body["data"]["aiUsage"] == []


@respx.mock
def test_ai_usage_maps_history_page(gql_app: FastAPI) -> None:
    tid = str(uuid.uuid4())
    uid = "11111111-1111-1111-1111-111111111111"
    respx.get("http://ai.gql.test/api/v1/ai/usage/history").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                        "created_at": "2020-01-01T00:00:00Z",
                        "user_id": uid,
                        "model": "gpt-test",
                        "input_tokens": 1,
                        "output_tokens": 2,
                        "cost_usd": "0.000001",
                        "billing_mode": "none",
                        "budget_id": None,
                    }
                ],
                "total": 1,
                "limit": 50,
                "offset": 0,
            },
        )
    )
    q = """
    query {
      aiUsage { model userId inputTokens outputTokens cost }
    }
    """
    with TestClient(gql_app) as client:
        r = client.post(
            "/graphql",
            json={"query": q},
            headers=_auth_headers(tid),
        )
    assert r.status_code == 200
    body = r.json()
    assert "errors" not in body, body
    row = body["data"]["aiUsage"][0]
    assert row["model"] == "gpt-test"
    assert row["userId"] == uid
    assert row["inputTokens"] == 1
    assert row["outputTokens"] == 2
    assert row["cost"] == "0.000001"
