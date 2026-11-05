"""Client credentials become one verified upstream authority, without ambiguity."""
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from api.infrastructure.security.api_key_exchange_jwt import try_decode_api_key_session_jwt
from test_api_key_edge import cross_app  # noqa: F401


@pytest.mark.parametrize("api_key", ["valid.key", ""])
@pytest.mark.parametrize("authorization", ["Bearer unverified.subject", "", "malformed"])
def test_edge_rejects_dual_credentials_before_validation(cross_app, monkeypatch, authorization, api_key):
    validate = AsyncMock(side_effect=AssertionError("ambiguous credential was validated"))
    monkeypatch.setattr("controlplane_edge.middleware.policy.validate_api_key_remote", validate)
    setup = AsyncMock(side_effect=AssertionError("ambiguous bearer was validated"))
    bearer = AsyncMock(side_effect=AssertionError("ambiguous bearer was validated"))
    monkeypatch.setattr("controlplane_edge.middleware.policy.resolve_setup_claims", setup)
    monkeypatch.setattr("controlplane_edge.middleware.policy.resolve_bearer_claims", bearer)
    with TestClient(cross_app) as client:
        response = client.get("/api/v1/users",
            headers={"Authorization": authorization, "X-Api-Key": api_key, "X-Tenant-ID": str(uuid.uuid4())})
    assert response.status_code == 401
    validate.assert_not_awaited()
    setup.assert_not_awaited()
    bearer.assert_not_awaited()


@respx.mock
def test_edge_exchanges_api_key_and_forwards_only_the_signed_identity(monkeypatch):
    from api.core.config import settings
    from fastapi import FastAPI
    from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting

    tenant, key_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("CPEDGE_API_KEYS_SERVICE_URL", "http://keys.test")
    monkeypatch.setenv("CPEDGE_USER_SERVICE_URL", "http://user.edge.test")
    monkeypatch.setattr(settings, "api_key_exchange_jwt_secret", "test-exchange-secret-at-least-32-chars!!")
    validate = AsyncMock(return_value={"valid": True, "key_id": str(key_id), "tenant_id": str(tenant), "scopes": [], "purpose": "ir"})
    monkeypatch.setattr("controlplane_edge.middleware.policy.validate_api_key_remote", validate)
    route = respx.get("http://user.edge.test/api/v1/users").mock(return_value=httpx.Response(200, json={"ok": True}))
    app = FastAPI()
    register_gateway_cross_cutting(app)
    with TestClient(app) as client:
        response = client.get("/api/v1/users", headers={"X-Api-Key": "verified.secret", "X-Tenant-ID": str(tenant)})
    assert response.status_code == 200, response.text
    validate.assert_awaited_once()
    forwarded = route.calls[0].request.headers
    assert "x-api-key" not in forwarded
    assert forwarded["x-tenant-id"] == str(tenant)
    claims = try_decode_api_key_session_jwt(forwarded["authorization"].removeprefix("Bearer "))
    assert claims is not None and claims["sub"] == "apikey:" + str(key_id)
    assert claims["https://spanopticon.dev/tenant_id"] == str(tenant) and claims["purpose"] == "ir"
