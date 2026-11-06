"""Edge binds tenant from the JWT claim. X-Tenant-ID is a cross-check."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from controlplane_identity.security.tenant_session_jwt import mint_tenant_session_jwt
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting


def _session(tenant_id: uuid.UUID) -> str:
    return mint_tenant_session_jwt(
        claims={
            "sub": "11111111-1111-1111-1111-111111111111",
            "email": "renter@example.com",
            "azp": "controlplane-frontend",
        },
        tenant_id=tenant_id,
        extra_roles=["renter"],
    )


def _raw_bearer() -> str:
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "11111111-1111-1111-1111-111111111111"}).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.sig"


@pytest.fixture
def probe_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    import controlplane_api.config as api_config

    monkeypatch.setattr(api_config.settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(api_config.settings, "keycloak_issuer", None)
    app = FastAPI()
    register_gateway_cross_cutting(app)

    @app.get("/probe")
    def probe(request: Request) -> dict[str, str | None]:
        tid = getattr(request.state, "tenant_id", None)
        return {"tenant_id": str(tid) if tid else None}

    return app


def test_session_claim_wins_and_header_must_match(probe_app: FastAPI) -> None:
    tid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    other = uuid.UUID("11111111-2222-3333-4444-555555555555")
    token = _session(tid)
    with TestClient(probe_app) as client:
        ok = client.get(
            "/probe",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Tenant-ID": str(tid),
            },
        )
        assert ok.status_code == 200
        assert ok.json()["tenant_id"] == str(tid)

        mismatch = client.get(
            "/probe",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Tenant-ID": str(other),
            },
        )
        assert mismatch.status_code == 403


def test_raw_jwt_does_not_bind_tenant_header(probe_app: FastAPI) -> None:
    victim = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    with TestClient(probe_app) as client:
        res = client.get(
            "/probe",
            headers={
                "Authorization": f"Bearer {_raw_bearer()}",
                "X-Tenant-ID": str(victim),
            },
        )
    assert res.status_code == 200
    assert res.json()["tenant_id"] is None
