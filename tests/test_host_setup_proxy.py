"""Exercise the real gateway policy and proxy with signed setup credentials."""
import time
import uuid
from types import SimpleNamespace

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from controlplane_api.config import settings
from controlplane_identity.security.keycloak_jwt import KeycloakJWTValidator
from controlplane_identity.security.tenant_session_jwt import mint_host_setup_session
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting
from controlplane_edge.public_paths import is_public_path

TID = str(uuid.uuid4())
# Stable registration fixture keeps parametrized case identities reproducible.
RID = "00000000-0000-4000-8000-000000000002"
AUTH_ROUTES = [("GET", "/auth/host-setup/me"), ("POST", "/auth/host-setup/enrollment/grant"), ("POST", "/auth/host-setup/session")]
SETUP_ROUTES = [("POST", "/api/v1/hypermesh/host-registrations"),
    ("GET", f"/api/v1/hypermesh/host-registrations/{RID}"),
    ("POST", f"/api/v1/hypermesh/host-registrations/{RID}/complete"),
    ("POST", "/api/v1/hypermesh/host-onboarding/approve-activation"),
    ("POST", "/api/v1/hypermesh/host-onboarding/approve-resume")]

@pytest.fixture
def setup_edge(monkeypatch):
    monkeypatch.setenv("CPEDGE_AUTH_SERVICE_URL", "http://auth.setup.test")
    monkeypatch.setenv("CPEDGE_HYPERMESH_SERVICE_URL", "http://hm.setup.test")
    monkeypatch.setenv("CPEDGE_RATE_LIMIT_PER_MINUTE", "5000")
    monkeypatch.setattr(settings, "api_key_exchange_jwt_secret", "setup-proxy-test-signing-secret-32-bytes!")
    monkeypatch.setattr(settings, "keycloak_jwks_url", "https://issuer.setup.test/certs")
    monkeypatch.setattr(settings, "keycloak_issuer", "https://issuer.setup.test")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    validator = KeycloakJWTValidator(settings.keycloak_jwks_url, settings.keycloak_issuer, "unused")
    validator._jwks_client = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key()))
    from controlplane_identity.security import keycloak_jwt
    from controlplane_edge import host_setup_auth
    monkeypatch.setattr(keycloak_jwt, "get_keycloak_jwt_validator", lambda: validator)
    monkeypatch.setattr(host_setup_auth, "get_keycloak_jwt_validator", lambda: validator)
    identity = {"azp": "hypermesh-host-setup", "sub": "owner", "email": "owner@example.com"}
    raw = jwt.encode({**identity, "iss": settings.keycloak_issuer, "aud": "hypermesh-host-setup", "exp": int(time.time())+300}, key, algorithm="RS256")
    setup = mint_host_setup_session(claims=identity, tenant_id=uuid.UUID(TID))
    app = FastAPI()
    register_gateway_cross_cutting(app)
    return app, raw, setup

@pytest.mark.parametrize("method,path", AUTH_ROUTES + SETUP_ROUTES)
@pytest.mark.parametrize("suffix", ["", "/"])
@respx.mock
def test_setup_tokens_reach_only_their_owner_service(setup_edge, method, path, suffix):
    app, raw, setup = setup_edge
    is_auth = path.startswith("/auth/")
    token = raw if is_auth else setup
    path += suffix
    upstream = ("http://auth.setup.test" if is_auth else "http://hm.setup.test") + path
    target = respx.request(method, upstream).mock(return_value=httpx.Response(200, json={"ok": True}))
    with TestClient(app) as client:
        response = client.request(method, path, headers={"Authorization": "Bearer " + token, "X-Tenant-ID": TID})
    assert response.status_code == 200, response.text
    assert target.calls[0].request.headers["authorization"] == "Bearer " + token
    assert not is_public_path(path, method)

@pytest.mark.parametrize("method,path", AUTH_ROUTES + SETUP_ROUTES)
@respx.mock
def test_wrong_token_kind_and_missing_credentials_never_reach_upstream(setup_edge, method, path):
    app, raw, setup = setup_edge
    wrong = setup if path.startswith("/auth/") else raw
    with TestClient(app) as client:
        for token in (wrong, "broken", ""):
            assert client.request(method, path, headers={"Authorization": "Bearer " + token}).status_code == 401
    assert not respx.calls

@pytest.mark.parametrize("method,path", [
    ("GET", "/auth/me"), ("POST", "/auth/switch-tenant"),
    ("GET", "/api/v1/users"), ("POST", "/api/v1/hypermesh/leases"),
    ("POST", f"/api/v1/hypermesh/host-registrations/{RID}/decision"),
    ("DELETE", f"/api/v1/hypermesh/host-registrations/{RID}"),
    ("GET", "/auth/host-setup/me/extra"),
    ("POST", "/api/v1/hypermesh/host-registrations/not-a-uuid/complete"),
])
@respx.mock
def test_setup_tokens_cannot_use_other_methods_or_paths(setup_edge, method, path):
    app, raw, setup = setup_edge
    with TestClient(app) as client:
        for token in (raw, setup):
            assert client.request(method, path, headers={"Authorization": "Bearer " + token}).status_code == 401
    assert not respx.calls

@respx.mock
def test_setup_session_tenant_mismatch_is_rejected_at_edge(setup_edge):
    app, _, setup = setup_edge
    with TestClient(app) as client:
        response = client.post(SETUP_ROUTES[0][1], headers={"Authorization": "Bearer " + setup, "X-Tenant-ID": str(uuid.uuid4())})
    assert response.status_code == 403
    assert not respx.calls


@pytest.mark.parametrize("configured", [True, False])
@respx.mock
def test_unsigned_setup_token_never_uses_development_fallback(setup_edge, monkeypatch, configured):
    app, _, _ = setup_edge
    if not configured:
        monkeypatch.setattr(settings, "keycloak_jwks_url", None)
        monkeypatch.setattr(settings, "keycloak_issuer", None)
    token = jwt.encode({"sub": "owner", "azp": "hypermesh-host-setup", "purpose": "host_setup", "tenant_id": TID}, key="", algorithm="none")
    with TestClient(app) as client:
        for method, path in AUTH_ROUTES + SETUP_ROUTES + [("GET", "/auth/me")]:
            assert client.request(method, path, headers={"Authorization": "Bearer " + token}).status_code == 401
    assert not respx.calls
