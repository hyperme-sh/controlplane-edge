"""Host agent enroll / device_secret routes skip gateway JWT; browse stays tight."""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from controlplane_edge.public_paths import is_public_path
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting

JOB_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
CPEDGE_AUTH_DETAIL = "Authorization Bearer token or valid X-Api-Key required"


@pytest.fixture
def agent_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("CPEDGE_HYPERMESH_SERVICE_URL", "http://hm.agent.test")
    monkeypatch.setenv("CPEDGE_HYPERMESH_GATEWAY_SERVICE_URL", "http://hmr.agent.test")
    monkeypatch.setenv("CPEDGE_RATE_LIMIT_PER_MINUTE", "5000")
    import api.core.config as api_config

    monkeypatch.setattr(api_config.settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(api_config.settings, "keycloak_issuer", None)

    app = FastAPI(title="Gateway host agent")
    register_gateway_cross_cutting(app)
    return app


def test_hypermesh_agent_enroll_is_public_post_only() -> None:
    assert is_public_path("/api/v1/hypermesh/agent/enroll", "POST") is True
    assert is_public_path("/api/v1/hypermesh/agent/enroll/", "POST") is True
    assert is_public_path("/api/v1/hypermesh/agent/enroll", "GET") is False
    assert is_public_path("/api/v1/hypermesh/agent/enroll", "PUT") is False
    assert is_public_path("/api/v1/hypermesh/agent/enroll", "DELETE") is False


def test_hypermesh_agent_device_secret_routes_are_public() -> None:
    assert is_public_path("/api/v1/hypermesh/agent/heartbeat", "POST") is True
    assert is_public_path("/api/v1/hypermesh/agent/heartbeat/", "POST") is True
    assert is_public_path("/api/v1/hypermesh/agent/jobs", "GET") is True
    assert is_public_path("/api/v1/hypermesh/agent/jobs/", "GET") is True
    assert is_public_path(f"/api/v1/hypermesh/agent/jobs/{JOB_ID}/result", "POST") is True
    assert is_public_path(f"/api/v1/hypermesh/agent/jobs/{JOB_ID}/result/", "POST") is True
    assert is_public_path("/api/v1/hypermesh/agent/scorecard", "POST") is True
    assert is_public_path("/api/v1/hypermesh/agent/scorecard/", "POST") is True
    assert is_public_path("/api/v1/hypermesh/agent/scorecard", "GET") is False
    assert is_public_path("/api/v1/hypermesh/agent/tunnel", "GET") is True
    assert is_public_path("/api/v1/hypermesh/agent/tunnel/ack", "POST") is True
    assert is_public_path("/api/v1/hypermesh/agent/tunnel/peer", "POST") is True
    assert is_public_path("/api/v1/hypermesh/agent/tunnel/peer/", "POST") is True
    assert is_public_path("/api/v1/hypermesh/agent/tunnel/peer", "GET") is False
    assert is_public_path("/api/v1/hypermesh/agent/tunnel/peer", "PUT") is False
    assert is_public_path("/api/v1/hypermesh/agent/tunnel/peer", "DELETE") is False
    assert is_public_path("/api/v1/hypermesh/agent/updates/test", "GET") is True
    assert is_public_path("/api/v1/hypermesh/agent/updates/prod", "GET") is True
    assert is_public_path("/api/v1/hypermesh/agent/updates/prod/", "GET") is True
    assert is_public_path("/api/v1/hypermesh/agent/updates/test", "POST") is False
    assert is_public_path("/api/v1/hypermesh/agent/updates/canary", "GET") is False
    assert is_public_path("/api/v1/hypermesh/agent/updates/test/extra", "GET") is False
    assert is_public_path("/api/v1/hypermesh/agent/updates", "GET") is False


def test_hypermesh_agent_allowlist_does_not_widen_browse_or_prefix() -> None:
    assert is_public_path("/api/v1/hypermesh/catalog", "GET") is True
    assert is_public_path("/api/v1/hypermesh/classes", "GET") is True
    assert is_public_path("/api/v1/hypermesh/nodes", "GET") is True
    assert is_public_path("/api/v1/hypermesh/catalog", "POST") is False
    assert is_public_path("/api/v1/hypermesh/classes", "POST") is False
    assert is_public_path("/api/v1/hypermesh", "GET") is False
    assert is_public_path("/api/v1/hypermesh/agent", "GET") is False
    assert is_public_path("/api/v1/hypermesh/agent/enroll/extra", "POST") is False
    assert is_public_path("/api/v1/hypermesh/agent/heartbeat", "GET") is False
    assert is_public_path("/api/v1/hypermesh/agent/jobs", "POST") is False
    assert is_public_path("/api/v1/hypermesh/agent/tunnel", "POST") is False
    assert is_public_path("/api/v1/hypermesh/agent/tunnel/peer/extra", "POST") is False
    assert is_public_path("/api/v1/hypermesh/agent/not-a-listed-route", "GET") is False
    assert is_public_path("/api/v1/hypermesh/agent/not-a-listed-route", "POST") is False
    assert is_public_path(f"/api/v1/hypermesh/agent/jobs/{JOB_ID}/result", "GET") is False
    assert is_public_path("/api/v1/hypermesh/agent/jobs/not-a-uuid/result", "POST") is False
    assert is_public_path(
        f"/api/v1/hypermesh/agent/jobs/{JOB_ID}/nested/result", "POST"
    ) is False
    assert is_public_path("/api/v1/hypermesh/devices", "GET") is False
    assert is_public_path(
        f"/api/v1/hypermesh/devices/{JOB_ID}/enroll-token", "POST"
    ) is False
    assert is_public_path("/api/v1/hypermesh/leases", "POST") is False
    assert is_public_path("/api/v1/hypermesh/renter/hosts", "GET") is False
    assert is_public_path("/api/v1/hypermesh/internal/gateways", "POST") is False
    assert is_public_path("/api/v1/hypermesh/renter/chat/completions", "POST") is False


@respx.mock
def test_unauthenticated_enroll_is_proxied(agent_app: FastAPI) -> None:
    """Live test-plane 401 was gateway JWT, not hypermesh-service enroll_token."""

    respx.post("http://hm.agent.test/api/v1/hypermesh/agent/enroll").mock(
        return_value=httpx.Response(
            200,
            json={
                "device_id": str(JOB_ID),
                "credential_prefix": "abcd1234",
                "device_secret": "hm_dev_secret",
                "role": "host",
            },
        )
    )
    with TestClient(agent_app) as client:
        enrolled = client.post(
            "/api/v1/hypermesh/agent/enroll",
            headers={
                "X-Tenant-ID": str(TENANT_ID),
                "Content-Type": "application/json",
            },
            json={"enroll_token": "one-time-token", "image_hash": "img-1"},
        )
    assert enrolled.status_code == 200, enrolled.text
    assert enrolled.json()["device_secret"] == "hm_dev_secret"
    assert "detail" not in enrolled.json()
    sent = respx.calls.last.request
    assert sent.headers["x-tenant-id"] == str(TENANT_ID)
    assert "authorization" not in sent.headers


@respx.mock
def test_enroll_get_still_requires_gateway_auth(agent_app: FastAPI) -> None:
    with TestClient(agent_app) as client:
        denied = client.get(
            "/api/v1/hypermesh/agent/enroll",
            headers={"X-Tenant-ID": str(TENANT_ID)},
        )
    assert denied.status_code == 401
    assert denied.json()["detail"] == CPEDGE_AUTH_DETAIL


@respx.mock
def test_device_secret_agent_routes_are_proxied(agent_app: FastAPI) -> None:
    headers = {
        "X-Tenant-ID": str(TENANT_ID),
        "Authorization": "Bearer hm_dev_not-a-jwt",
    }
    respx.post("http://hm.agent.test/api/v1/hypermesh/agent/heartbeat").mock(
        return_value=httpx.Response(200, json={"device_id": str(JOB_ID)})
    )
    respx.get("http://hm.agent.test/api/v1/hypermesh/agent/jobs").mock(
        return_value=httpx.Response(204)
    )
    respx.post(
        f"http://hm.agent.test/api/v1/hypermesh/agent/jobs/{JOB_ID}/result"
    ).mock(return_value=httpx.Response(200, json={"id": str(JOB_ID)}))
    respx.get("http://hm.agent.test/api/v1/hypermesh/agent/tunnel").mock(
        return_value=httpx.Response(204)
    )
    respx.post("http://hm.agent.test/api/v1/hypermesh/agent/tunnel/ack").mock(
        return_value=httpx.Response(200, json={"applied": True})
    )
    respx.post("http://hm.agent.test/api/v1/hypermesh/agent/tunnel/peer").mock(
        return_value=httpx.Response(200, json={"peer_public_key": "host-pub"})
    )
    respx.post("http://hm.agent.test/api/v1/hypermesh/agent/scorecard").mock(
        return_value=httpx.Response(200, json={"catalog_id": "llama-3.1-8b-q4"})
    )
    with TestClient(agent_app) as client:
        beat = client.post(
            "/api/v1/hypermesh/agent/heartbeat",
            headers=headers,
            json={"device_id": str(JOB_ID)},
        )
        jobs = client.get(
            "/api/v1/hypermesh/agent/jobs",
            headers=headers,
            params={"device_id": str(JOB_ID)},
        )
        result = client.post(
            f"/api/v1/hypermesh/agent/jobs/{JOB_ID}/result",
            headers=headers,
            json={"passed": True},
        )
        tunnel = client.get("/api/v1/hypermesh/agent/tunnel", headers=headers)
        ack = client.post(
            "/api/v1/hypermesh/agent/tunnel/ack",
            headers=headers,
            json={"applied": True},
        )
        peer = client.post(
            "/api/v1/hypermesh/agent/tunnel/peer",
            headers=headers,
            json={"peer_public_key": "host-pub"},
        )
        scorecard = client.post(
            "/api/v1/hypermesh/agent/scorecard",
            headers=headers,
            json={"device_id": str(JOB_ID), "catalog_id": "llama-3.1-8b-q4"},
        )
    assert beat.status_code == 200, beat.text
    assert jobs.status_code == 204
    assert result.status_code == 200, result.text
    assert tunnel.status_code == 204
    assert ack.status_code == 200, ack.text
    assert peer.status_code == 200, peer.text
    assert peer.json().get("detail") != "Invalid or missing JWT claims"
    assert scorecard.status_code == 200, scorecard.text
    peer_calls = [
        call.request
        for call in respx.calls
        if call.request.method == "POST"
        and call.request.url.path == "/api/v1/hypermesh/agent/tunnel/peer"
    ]
    assert len(peer_calls) == 1
    assert peer_calls[0].headers["authorization"] == "Bearer hm_dev_not-a-jwt"
    assert peer_calls[0].headers["x-tenant-id"] == str(TENANT_ID)


@respx.mock
def test_lease_and_device_mint_still_require_auth(agent_app: FastAPI) -> None:
    with TestClient(agent_app) as client:
        lease = client.post(
            "/api/v1/hypermesh/leases",
            headers={"X-Tenant-ID": str(TENANT_ID)},
            json={"kind": "p2_loaded_model"},
        )
        mint = client.post(
            f"/api/v1/hypermesh/devices/{JOB_ID}/enroll-token",
            headers={"X-Tenant-ID": str(TENANT_ID)},
            json={"role": "host"},
        )
        catalog_post = client.post(
            "/api/v1/hypermesh/catalog",
            headers={"X-Tenant-ID": str(TENANT_ID)},
            json={},
        )
    assert lease.status_code == 401
    assert mint.status_code == 401
    assert catalog_post.status_code == 401
    assert lease.json()["detail"] == CPEDGE_AUTH_DETAIL
    assert mint.json()["detail"] == CPEDGE_AUTH_DETAIL


@respx.mock
def test_tunnel_peer_non_device_bearer_is_not_a_success(agent_app: FastAPI) -> None:
    """Public agent paths skip gateway JWT and forward the bearer.

    hypermesh-service ``_require_device_auth`` rejects anything that is not
    a device secret. A garbage token and an ``hm_site_`` token must not
    receive a 2xx from this route. The edge propagates the service 401
    rather than answering success itself.
    """

    route = respx.post("http://hm.agent.test/api/v1/hypermesh/agent/tunnel/peer").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid device credential"})
    )
    body = {"peer_public_key": "a" * 44}
    with TestClient(agent_app) as client:
        garbage = client.post(
            "/api/v1/hypermesh/agent/tunnel/peer",
            headers={
                "X-Tenant-ID": str(TENANT_ID),
                "Authorization": "Bearer not-a-jwt",
            },
            json=body,
        )
        site = client.post(
            "/api/v1/hypermesh/agent/tunnel/peer",
            headers={
                "X-Tenant-ID": str(TENANT_ID),
                "Authorization": "Bearer hm_site_cottage-token",
            },
            json=body,
        )
    assert garbage.status_code == 401, garbage.text
    assert site.status_code == 401, site.text
    assert not 200 <= garbage.status_code < 300
    assert not 200 <= site.status_code < 300
    assert garbage.json()["detail"] == "Invalid device credential"
    assert site.json()["detail"] == "Invalid device credential"
    assert route.call_count == 2
    assert [call.request.headers["authorization"] for call in route.calls] == [
        "Bearer not-a-jwt",
        "Bearer hm_site_cottage-token",
    ]


@respx.mock
def test_agent_update_channel_is_proxied_with_device_secret(agent_app: FastAPI) -> None:
    respx.get("http://hm.agent.test/api/v1/hypermesh/agent/updates/test").mock(
        return_value=httpx.Response(
            200,
            json={
                "channel": "test",
                "version": "0.0.0",
                "commit": "abc",
                "artifacts": [],
            },
        )
    )
    with TestClient(agent_app) as client:
        got = client.get(
            "/api/v1/hypermesh/agent/updates/test",
            headers={
                "X-Tenant-ID": str(TENANT_ID),
                "Authorization": "Bearer hm_dev_not-a-jwt",
            },
        )
        denied = client.get("/api/v1/hypermesh/agent/updates/canary")
    assert got.status_code == 200, got.text
    assert denied.status_code == 401
    sent = respx.calls.last.request
    assert sent.url.path == "/api/v1/hypermesh/agent/updates/test"
    assert sent.headers["authorization"] == "Bearer hm_dev_not-a-jwt"
    assert sent.headers["x-tenant-id"] == str(TENANT_ID)


def test_unlisted_hypermesh_agent_path_stays_non_public(agent_app: FastAPI) -> None:
    assert is_public_path("/api/v1/hypermesh/agent/not-a-listed-route", "POST") is False
    with TestClient(agent_app) as client:
        denied = client.post(
            "/api/v1/hypermesh/agent/not-a-listed-route",
            headers={
                "X-Tenant-ID": str(TENANT_ID),
                "Authorization": "Bearer hm_dev_not-a-jwt",
            },
            json={},
        )
    assert denied.status_code == 401
    assert denied.json()["detail"] == "Invalid or missing JWT claims"


@pytest.mark.parametrize("suffix", ["check", "heartbeat", "tunnel", "certification/plan",
                                    "certification/result", "certification/activation"])
@respx.mock
def test_onboarding_device_routes_reach_service_verification(agent_app, suffix):
    path = "/api/v1/hypermesh/agent/onboarding/" + suffix
    route = respx.post("http://hm.agent.test" + path).mock(
        return_value=httpx.Response(401, json={"detail": "registered device required"}))
    with TestClient(agent_app) as client:
        response = client.post(path, headers={"Authorization": "Bearer hm_dev_test",
                                              "X-Tenant-ID": str(TENANT_ID)}, json={})
    assert response.status_code == 401
    assert response.json()["detail"] == "registered device required"
    assert route.call_count == 1
    assert route.calls[0].request.headers["authorization"] == "Bearer hm_dev_test"
    assert not is_public_path(path, "GET")
    assert not is_public_path(path + "/extra", "POST")
    assert not is_public_path("/api/v1/hypermesh/host-onboarding/approve-activation", "POST")

def test_resume_uses_device_auth_but_owner_approval_still_requires_jwt():
    path = "/api/v1/hypermesh/agent/onboarding/certification/resume"
    assert is_public_path(path, "POST")
    assert not is_public_path(path, "GET")
    assert not is_public_path(path + "/extra", "POST")
    assert not is_public_path("/api/v1/hypermesh/host-onboarding/approve-resume", "POST")
