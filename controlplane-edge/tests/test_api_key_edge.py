"""Gateway accepts X-Api-Key when api-keys-service validates (mocked)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from controlplane_edge.aggregation import register_aggregation_routes
from controlplane_edge.graphql.register import register_graphql_routes
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting


@pytest.fixture
def cross_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("CPEDGE_AUTH_SERVICE_URL", "http://auth.cc.test")
    monkeypatch.setenv("CPEDGE_USER_SERVICE_URL", "http://user.cc.test")
    monkeypatch.setenv("CPEDGE_RATE_LIMIT_PER_MINUTE", "5000")
    monkeypatch.setenv("CPEDGE_API_KEYS_SERVICE_URL", "http://keys.test")
    app = FastAPI()
    register_gateway_cross_cutting(app)
    register_aggregation_routes(app)
    register_graphql_routes(app)
    return app


def test_api_key_passes_auth_for_graphql(cross_app: FastAPI) -> None:
    tid = uuid.uuid4()
    kid = uuid.uuid4()
    respx.get("http://auth.cc.test/openapi.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "openapi": "3.0.0",
                "paths": {},
                "info": {"title": "a", "version": "1"},
                "components": {"schemas": {}},
            },
        )
    )
    respx.get("http://user.cc.test/openapi.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "openapi": "3.0.0",
                "paths": {},
                "info": {"title": "u", "version": "1"},
                "components": {"schemas": {}},
            },
        )
    )

    async def fake_validate(**kwargs):
        return {
            "valid": True,
            "key_id": str(kid),
            "tenant_id": str(tid),
            "scopes": ["marketplace.read"],
        }

    with patch(
        "controlplane_edge.middleware.policy.validate_api_key_remote",
        new=AsyncMock(side_effect=fake_validate),
    ):
        client = TestClient(cross_app)
        r = client.post(
            "/graphql",
            json={"query": "{ __typename }"},
            headers={
                "x-api-key": "pref.secretpart",
                "x-tenant-id": str(tid),
            },
        )
        assert r.status_code == 200, r.text
