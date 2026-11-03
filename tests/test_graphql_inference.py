"""runInference mutation mocked against ai-service."""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.infrastructure.security.tenant_session_jwt import mint_tenant_session_jwt
from controlplane_edge.graphql.register import register_graphql_routes


def _auth_headers(tenant_id: str) -> dict[str, str]:
    tid = uuid.UUID(tenant_id)
    token = mint_tenant_session_jwt(
        claims={
            "sub": "11111111-1111-1111-1111-111111111111",
            "email": "renter@example.com",
        },
        tenant_id=tid,
        extra_roles=["renter"],
    )
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}


@pytest.fixture
def gql_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("CPEDGE_AI_SERVICE_URL", "http://ai.gql.test")
    app = FastAPI()
    register_graphql_routes(app)
    return app


@respx.mock
def test_run_inference(gql_app: FastAPI) -> None:
    tid = str(uuid.uuid4())
    iid = str(uuid.uuid4())
    respx.post("http://ai.gql.test/api/v1/ai/inference").mock(
        return_value=httpx.Response(
            200,
            json={
                "text": "hello",
                "model": "m",
                "input_tokens": 1,
                "output_tokens": 2,
                "cost_usd": "0.01",
                "inference_id": iid,
            },
        )
    )
    mut = """
    mutation ($input: RunInferenceInput!) {
      runInference(input: $input) {
        text
        model
        inferenceId
      }
    }
    """
    with TestClient(gql_app) as client:
        r = client.post(
            "/graphql",
            json={
                "query": mut,
                "variables": {
                    "input": {"prompt": "hi", "model": "m", "billingMode": "none"},
                },
            },
            headers=_auth_headers(tid),
        )
    assert r.status_code == 200
    body = r.json()
    assert "errors" not in body, body
    ri = body["data"]["runInference"]
    assert ri["text"] == "hello"
    assert ri["inferenceId"] == iid
