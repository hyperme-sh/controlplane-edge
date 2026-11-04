"""The exact current-owner read accepts its service credential through the edge."""

import uuid

import httpx
import pytest
import respx
from controlplane_api.config import settings
from controlplane_edge.public_paths import is_public_path
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting
from fastapi import FastAPI
from fastapi.testclient import TestClient

PATH = "/api/v1/hypermesh/host-management/ownership"
TENANT = str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
BODY = {"host_org_id": "22222222-2222-4222-8222-222222222222", "subject": "owner"}


@pytest.fixture
def edge(monkeypatch):
    monkeypatch.setenv("CPEDGE_HYPERMESH_SERVICE_URL", "http://owner.edge.test")
    monkeypatch.setenv("CPEDGE_RATE_LIMIT_PER_MINUTE", "5000")
    monkeypatch.setattr(settings, "hypermesh_internal_token", "owner-read-secret")
    monkeypatch.setattr(settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(settings, "keycloak_issuer", None)
    app = FastAPI()
    register_gateway_cross_cutting(app)
    return app


@pytest.mark.parametrize("upstream_status", [200, 401, 403])
@respx.mock
def test_service_owner_read_preserves_credential_scope_and_owner_decision(
    edge, upstream_status
):
    route = respx.post("http://owner.edge.test" + PATH).mock(
        return_value=httpx.Response(upstream_status, json={"source": "owner"})
    )
    with TestClient(edge) as client:
        response = client.post(
            PATH,
            headers={"X-Internal-Token": "owner-read-secret", "X-Tenant-ID": TENANT},
            json=BODY,
        )
    assert response.status_code == upstream_status
    assert route.call_count == 1
    sent = route.calls.last.request
    assert sent.headers["x-internal-token"] == "owner-read-secret"
    assert sent.headers["x-tenant-id"] == TENANT
    assert "authorization" not in sent.headers
    assert sent.content == httpx.Request("POST", "http://unused", json=BODY).content
    assert not is_public_path(PATH, "POST")


@pytest.mark.parametrize(
    "provided,expected",
    [(None, "secret"), ("wrong", "secret"), ("secret", ""), ("", "secret")],
)
@respx.mock
def test_missing_wrong_or_unconfigured_internal_credential_cannot_reach_owner(
    edge, monkeypatch, provided, expected
):
    monkeypatch.setattr(settings, "hypermesh_internal_token", expected)
    headers = {"X-Tenant-ID": TENANT}
    if provided is not None:
        headers["X-Internal-Token"] = provided
    with TestClient(edge) as client:
        response = client.post(PATH, headers=headers, json=BODY)
    assert response.status_code == 401
    assert not respx.calls


@pytest.mark.parametrize("tenant", [None, "not-a-tenant"])
@respx.mock
def test_internal_credential_still_requires_valid_tenant(edge, tenant):
    headers = {"X-Internal-Token": "owner-read-secret"}
    if tenant is not None:
        headers["X-Tenant-ID"] = tenant
    with TestClient(edge) as client:
        response = client.post(PATH, headers=headers, json=BODY)
    assert response.status_code == 401
    assert not respx.calls


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", PATH),
        ("PUT", PATH),
        ("DELETE", PATH),
        ("POST", PATH + "/extra"),
        ("POST", "/api/v1/hypermesh/host-management/context"),
        ("POST", "/api/v1/hypermesh/leases"),
    ],
)
@respx.mock
def test_internal_credential_does_not_open_adjacent_routes_or_methods(
    edge, method, path
):
    with TestClient(edge) as client:
        response = client.request(
            method,
            path,
            headers={"X-Internal-Token": "owner-read-secret", "X-Tenant-ID": TENANT},
            json=BODY,
        )
    assert response.status_code == 401
    assert not respx.calls


@respx.mock
def test_internal_owner_read_remains_rate_limited(edge):
    class Deny:
        def allow(self, tenant, subject):
            assert str(tenant) == TENANT
            return False

    edge.state.gateway_rate_limiter = Deny()
    with TestClient(edge) as client:
        response = client.post(
            PATH,
            headers={"X-Internal-Token": "owner-read-secret", "X-Tenant-ID": TENANT},
            json=BODY,
        )
    assert response.status_code == 429
    assert not respx.calls
