"""HTTP reverse-proxy behavior for extracted-service prefixes."""

from __future__ import annotations

import base64
import json
import uuid

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from controlplane_edge.public_paths import is_public_path
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting


def _fake_bearer(sub: str = "11111111-1111-1111-1111-111111111111", tenant: str | None = None) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub, **({"tenant_id": tenant} if tenant else {})}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


@pytest.fixture
def edge_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("CPEDGE_USER_SERVICE_URL", "http://user.edge.test")
    monkeypatch.setenv("CPEDGE_AUTH_SERVICE_URL", "http://auth.edge.test")
    monkeypatch.setenv("CPEDGE_AI_SERVICE_URL", "http://ai.edge.test")
    monkeypatch.setenv("CPEDGE_PAYMENT_SERVICE_URL", "http://pay.edge.test")
    monkeypatch.setenv("CPEDGE_VERIFICATION_SERVICE_URL", "http://verification.edge.test")
    monkeypatch.setenv("CPEDGE_RATE_LIMIT_PER_MINUTE", "5000")
    import controlplane_api.config as api_config

    monkeypatch.setattr(api_config.settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(api_config.settings, "keycloak_issuer", None)

    app = FastAPI()

    @app.get("/api/v1/tenants")
    def _tenants():
        return [{"id": "monolith-tenant"}]

    @app.get("/api/v1/roles/")
    def _roles():
        return {"items": [{"name": "admin"}]}

    @app.get("/api/v1/account/me")
    def _me():
        return {"email": "monolith@example.com"}

    @app.put("/api/v1/ai/set_model_preference/{model_name}")
    def _pref(model_name: str):
        return {"model_name": model_name, "source": "monolith"}

    register_gateway_cross_cutting(app)
    return app


def _auth_headers() -> dict[str, str]:
    tenant = str(uuid.uuid4())
    return {
        "Authorization": f"Bearer {_fake_bearer(tenant=tenant)}",
        "X-Tenant-ID": tenant,
    }


@respx.mock
def test_users_proxied_to_user_service(edge_app: FastAPI) -> None:
    respx.get("http://user.edge.test/api/v1/users").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"email": "from-user-service"}], "total": 1, "limit": 50, "offset": 0},
        )
    )
    with TestClient(edge_app) as client:
        r = client.get("/api/v1/users", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["items"][0]["email"] == "from-user-service"


@respx.mock
def test_proxy_forwards_query_and_bearer(edge_app: FastAPI) -> None:
    route = respx.get("http://user.edge.test/api/v1/users").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0, "limit": 10, "offset": 0})
    )
    headers = _auth_headers()
    with TestClient(edge_app) as client:
        r = client.get("/api/v1/users", params={"limit": 10, "q": "ada"}, headers=headers)
    assert r.status_code == 200
    assert route.called
    sent = route.calls[0].request
    assert sent.url.params["limit"] == "10"
    assert sent.url.params["q"] == "ada"
    assert sent.headers["authorization"] == headers["Authorization"]
    assert sent.headers["x-tenant-id"] == headers["X-Tenant-ID"]


@respx.mock
def test_groups_and_organizations_proxied(edge_app: FastAPI) -> None:
    respx.get("http://user.edge.test/api/v1/groups").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0, "limit": 50, "offset": 0})
    )
    respx.post("http://user.edge.test/api/v1/organizations").mock(
        return_value=httpx.Response(201, json={"id": "org-1", "legal_name": "Acme"})
    )
    with TestClient(edge_app) as client:
        g = client.get("/api/v1/groups", headers=_auth_headers())
        o = client.post(
            "/api/v1/organizations",
            headers=_auth_headers(),
            json={"legal_name": "Acme"},
        )
    assert g.status_code == 200
    assert o.status_code == 201
    assert o.json()["legal_name"] == "Acme"


def test_monolith_leftover_tenants_roles_account_stay_local(edge_app: FastAPI) -> None:
    with TestClient(edge_app) as client:
        t = client.get("/api/v1/tenants", headers=_auth_headers())
        roles = client.get("/api/v1/roles/", headers=_auth_headers())
        me = client.get("/api/v1/account/me", headers=_auth_headers())
        pref = client.put("/api/v1/ai/set_model_preference/llama", headers=_auth_headers())
    assert t.json() == [{"id": "monolith-tenant"}]
    assert roles.json()["items"][0]["name"] == "admin"
    assert me.json()["email"] == "monolith@example.com"
    assert pref.json() == {"model_name": "llama", "source": "monolith"}


@respx.mock
def test_ai_inference_proxied_but_chat_leftover_is_not(edge_app: FastAPI) -> None:
    respx.post("http://ai.edge.test/api/v1/ai/inference").mock(
        return_value=httpx.Response(200, json={"output": "ok", "source": "ai-service"})
    )
    with TestClient(edge_app) as client:
        inf = client.post(
            "/api/v1/ai/inference",
            headers=_auth_headers(),
            json={"prompt": "hi"},
        )
        leftover = client.put("/api/v1/ai/set_model_preference/llama", headers=_auth_headers())
    assert inf.json()["source"] == "ai-service"
    assert leftover.json()["source"] == "monolith"


@respx.mock
def test_auth_login_is_public_and_proxied(edge_app: FastAPI) -> None:
    respx.post("http://auth.edge.test/auth/login").mock(
        return_value=httpx.Response(
            200,
            json={"authorization_url": "http://keycloak/auth", "state": "s"},
        )
    )
    with TestClient(edge_app) as client:
        r = client.post("/auth/login", json={})
    assert r.status_code == 200
    assert r.json()["state"] == "s"


def test_unconfigured_upstream_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CPEDGE_RATE_LIMIT_PER_MINUTE", "5000")
    import controlplane_api.config as api_config

    monkeypatch.setattr(api_config.settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(api_config.settings, "keycloak_issuer", None)
    app = FastAPI()
    register_gateway_cross_cutting(app)
    with TestClient(app) as client:
        r = client.get("/api/v1/users", headers=_auth_headers())
    assert r.status_code == 503
    assert r.json()["service"] == "user"


@respx.mock
def test_upstream_error_returns_502(edge_app: FastAPI) -> None:
    respx.get("http://user.edge.test/api/v1/users").mock(side_effect=httpx.ConnectError("boom"))
    with TestClient(edge_app) as client:
        r = client.get("/api/v1/users", headers=_auth_headers())
    assert r.status_code == 502
    assert r.json()["service"] == "user"


@respx.mock
def test_hypermesh_smoke_session_is_public_and_proxied(edge_app: FastAPI) -> None:
    """GitHub OIDC is not a Keycloak JWT. The edge must proxy it anyway."""

    route = respx.post("http://auth.edge.test/auth/hypermesh-smoke/session").mock(
        return_value=httpx.Response(200, json={"token_type": "Bearer"})
    )
    bearer = _fake_bearer(sub="repo:FyberLabs/panopticon:environment:test")
    with TestClient(edge_app) as client:
        missing = client.post("/auth/hypermesh-smoke/session", json={})
        present = client.post(
            "/auth/hypermesh-smoke/session",
            headers={"Authorization": f"Bearer {bearer}"},
            json={},
        )
    assert is_public_path("/auth/hypermesh-smoke/session", "POST") is True
    assert missing.status_code == 200
    assert present.status_code == 200
    assert present.json() == {"token_type": "Bearer"}
    assert route.calls[-1].request.headers["authorization"] == f"Bearer {bearer}"


@respx.mock
def test_hypermesh_smoke_session_rejects_get_and_subpath(edge_app: FastAPI) -> None:
    """POST /auth/hypermesh-smoke/session is exact. GET and subpaths stay closed."""

    session = respx.post("http://auth.edge.test/auth/hypermesh-smoke/session").mock(
        return_value=httpx.Response(200, json={"token_type": "Bearer"})
    )
    session_get = respx.get("http://auth.edge.test/auth/hypermesh-smoke/session").mock(
        return_value=httpx.Response(200, json={"token_type": "Bearer"})
    )
    nested = respx.post("http://auth.edge.test/auth/hypermesh-smoke/session/x").mock(
        return_value=httpx.Response(200, json={"token_type": "Bearer"})
    )
    assert is_public_path("/auth/hypermesh-smoke/session", "GET") is False
    assert is_public_path("/auth/hypermesh-smoke/session/x", "POST") is False
    with TestClient(edge_app) as client:
        got = client.get("/auth/hypermesh-smoke/session")
        subpath = client.post("/auth/hypermesh-smoke/session/x", json={})
    assert got.status_code == 401
    assert subpath.status_code == 401
    assert got.json()["detail"] == (
        "Authorization Bearer token or valid X-Api-Key required"
    )
    assert session.called is False
    assert session_get.called is False
    assert nested.called is False


@respx.mock
def test_issuer_session_end_is_public_and_proxied(edge_app: FastAPI) -> None:
    route = respx.post(
        "http://pay.edge.test/api/v1/payments/connect/access-session/end"
    ).mock(return_value=httpx.Response(200, json={"ended": True}))
    with TestClient(edge_app) as client:
        missing = client.get("/api/v1/payments/connect/access-session/end")
        ended = client.post(
            "/api/v1/payments/connect/access-session/end",
            headers={"X-Auth-Session-Token": "original", "X-Tenant-ID": str(uuid.uuid4())},
        )
        extra = client.post("/api/v1/payments/connect/access-session/end/extra")
    assert missing.status_code == 401
    assert ended.status_code == 200 and ended.json() == {"ended": True}
    assert extra.status_code == 401
    assert route.call_count == 1
    assert route.calls.last.request.headers["x-auth-session-token"] == "original"


@respx.mock
def test_stripe_webhook_is_public_and_proxied(edge_app: FastAPI, operator_payment_routes) -> None:
    respx.post("http://pay.edge.test/api/v1/payments/stripe/webhook").mock(
        return_value=httpx.Response(200, json={"received": True})
    )
    with TestClient(edge_app) as client:
        r = client.post("/api/v1/payments/stripe/webhook", content=b"{}")
    assert r.status_code == 200
    assert r.json() == {"received": True}


def test_users_require_auth_when_not_public(edge_app: FastAPI, operator_payment_routes) -> None:
    assert is_public_path("/api/v1/users", "GET") is False
    assert is_public_path("/auth/login", "POST") is True
    assert is_public_path("/auth/hypermesh-smoke/session", "POST") is True
    assert is_public_path("/auth/hypermesh-smoke/session", "GET") is False
    assert is_public_path("/auth/hypermesh-smoke/session/x", "POST") is False
    assert is_public_path("/auth/enrollment/marketplace", "GET") is True
    assert is_public_path("/auth/enrollment/marketplace", "POST") is False
    assert is_public_path("/auth/enrollment/marketplace/other", "GET") is False
    assert is_public_path("/auth/enrollment/grant", "POST") is False
    assert is_public_path("/auth/me", "GET") is False
    assert is_public_path("/api/v1/payments/stripe/webhook", "POST") is True
    assert is_public_path("/api/v1/payments/connect/access-session/end", "POST") is True
    assert is_public_path("/api/v1/payments/connect/access-session/end/", "POST") is True
    assert is_public_path("/api/v1/payments/connect/access-session/end", "GET") is False
    assert is_public_path("/api/v1/payments/connect/access-session/end/extra", "POST") is False
    assert is_public_path("/api/v1/hypermesh/catalog", "GET") is True
    assert is_public_path("/api/v1/hypermesh/classes", "GET") is True
    assert is_public_path("/api/v1/hypermesh/nodes", "GET") is True
    assert is_public_path("/api/v1/hypermesh/agent/enroll", "POST") is True
    assert is_public_path("/api/v1/hypermesh/agent/enroll", "GET") is False
    assert is_public_path("/api/v1/hypermesh/leases", "POST") is False
    with TestClient(edge_app) as client:
        r = client.get("/api/v1/users")
    assert r.status_code == 401
    assert is_public_path("/api/v1/auditor/v0/tickets", "POST") is False
    assert is_public_path("/api/v1/aiuditor/connections", "GET") is False
    assert is_public_path("/api/v1/aiuditor/connections", "POST") is False


@respx.mock
def test_site_machine_token_passes_through_to_auditor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CPEDGE_HYPERMESH_SERVICE_URL", "http://hm.edge.test")
    monkeypatch.setenv("CPEDGE_RATE_LIMIT_PER_MINUTE", "5000")
    import controlplane_api.config as api_config

    monkeypatch.setattr(api_config.settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(api_config.settings, "keycloak_issuer", None)
    app = FastAPI()
    register_gateway_cross_cutting(app)
    route = respx.post("http://hm.edge.test/api/v1/auditor/v0/tickets").mock(
        return_value=httpx.Response(200, json={"ticket_id": "t1", "status": "open"})
    )
    with TestClient(app) as client:
        garbage = client.post("/api/v1/auditor/v0/tickets", json={})
        ok = client.post(
            "/api/v1/auditor/v0/tickets",
            headers={"Authorization": "Bearer hm_site_cottage-token"},
            json={"schema": "fyber.auditor.ticket/v0"},
        )
    assert garbage.status_code == 401
    assert ok.status_code == 200
    assert route.called
    assert route.calls[0].request.headers["authorization"] == "Bearer hm_site_cottage-token"


@respx.mock
def test_site_machine_token_passes_through_to_hypermesh_site_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CPEDGE_HYPERMESH_SERVICE_URL", "http://hm.edge.test")
    monkeypatch.setenv("CPEDGE_RATE_LIMIT_PER_MINUTE", "5000")
    import controlplane_api.config as api_config

    monkeypatch.setattr(api_config.settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(api_config.settings, "keycloak_issuer", None)
    app = FastAPI()
    register_gateway_cross_cutting(app)
    route = respx.post("http://hm.edge.test/api/v1/hypermesh/site/jobs").mock(
        return_value=httpx.Response(201, json={"job_id": "j1", "kind": "sell_pause"})
    )
    with TestClient(app) as client:
        garbage = client.post("/api/v1/hypermesh/site/jobs", json={})
        ok = client.post(
            "/api/v1/hypermesh/site/jobs",
            headers={"Authorization": "Bearer hm_site_cottage-token"},
            json={"kind": "sell_pause", "device_id": "a6400000-0640-4000-8000-000000000001"},
        )
    assert garbage.status_code == 401
    assert ok.status_code == 201
    assert route.called
    assert route.calls[0].request.headers["authorization"] == "Bearer hm_site_cottage-token"


@respx.mock
def test_site_machine_token_passes_through_to_hypermesh_site_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CPEDGE_HYPERMESH_SERVICE_URL", "http://hm.edge.test")
    monkeypatch.setenv("CPEDGE_RATE_LIMIT_PER_MINUTE", "5000")
    import controlplane_api.config as api_config

    monkeypatch.setattr(api_config.settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(api_config.settings, "keycloak_issuer", None)
    app = FastAPI()
    register_gateway_cross_cutting(app)
    device_id = "a6400000-0640-4000-8000-000000000001"
    route = respx.get(f"http://hm.edge.test/api/v1/hypermesh/site/devices/{device_id}").mock(
        return_value=httpx.Response(200, json={"device_id": device_id, "sell_state": "paused"})
    )
    with TestClient(app) as client:
        garbage = client.get(f"/api/v1/hypermesh/site/devices/{device_id}")
        ok = client.get(
            f"/api/v1/hypermesh/site/devices/{device_id}",
            headers={"Authorization": "Bearer hm_site_cottage-token"},
        )
    assert garbage.status_code == 401
    assert ok.status_code == 200
    assert route.called
    assert route.calls[0].request.headers["authorization"] == "Bearer hm_site_cottage-token"


@respx.mock
def test_site_machine_token_passes_through_to_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CPEDGE_HYPERMESH_SERVICE_URL", "http://hm.edge.test")
    monkeypatch.setenv("CPEDGE_RATE_LIMIT_PER_MINUTE", "5000")
    import controlplane_api.config as api_config

    monkeypatch.setattr(api_config.settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(api_config.settings, "keycloak_issuer", None)
    app = FastAPI()
    register_gateway_cross_cutting(app)
    route = respx.post("http://hm.edge.test/api/v1/grants/v0/grants").mock(
        return_value=httpx.Response(200, json={"grant_id": "g1", "status": "proposed"})
    )
    with TestClient(app) as client:
        garbage = client.post("/api/v1/grants/v0/grants", json={})
        ok = client.post(
            "/api/v1/grants/v0/grants",
            headers={"Authorization": "Bearer hm_site_cottage-token"},
            json={"schema": "fyber.privilege_grant/v0"},
        )
    assert garbage.status_code == 401
    assert ok.status_code == 200
    assert route.called
    assert route.calls[0].request.headers["authorization"] == "Bearer hm_site_cottage-token"


@respx.mock
def test_portal_controls_proxy_preserves_tenant_auth(edge_app: FastAPI) -> None:
    route = respx.get("http://user.edge.test/api/v1/me/portal-controls").mock(
        return_value=httpx.Response(200, json={"groups": ["host", "renter"]})
    )
    headers = _auth_headers()
    with TestClient(edge_app) as client:
        assert client.get("/api/v1/me/portal-controls").status_code == 401
        response = client.get("/api/v1/me/portal-controls", headers=headers)
    assert response.status_code == 200
    assert response.json()["groups"] == ["host", "renter"]
    assert len(route.calls) == 1
    assert route.calls[0].request.headers["authorization"] == headers["Authorization"]
    assert route.calls[0].request.headers["x-tenant-id"] == headers["X-Tenant-ID"]


@pytest.mark.parametrize("claim_name", ["canonical", "plain"])
@pytest.mark.parametrize("header_mode", ["absent", "matching", "mismatch"])
@respx.mock
def test_verified_tenant_binding(edge_app, monkeypatch, claim_name, header_mode):
    from controlplane_edge.middleware import policy
    tenant = str(uuid.uuid4())
    key = {"canonical": policy.TENANT_CLAIM,
           "plain": "tenant_id"}[claim_name]

    async def verified(_token):
        return {"sub": "user", key: tenant}

    monkeypatch.setattr(policy, "resolve_bearer_claims", verified)
    route = respx.get("http://user.edge.test/api/v1/users").respond(200, json={})
    headers = {"Authorization": "Bearer verified"}
    if header_mode != "absent":
        headers["X-Tenant-ID"] = tenant if header_mode == "matching" else str(uuid.uuid4())
    with TestClient(edge_app) as client:
        response = client.get("/api/v1/users", headers=headers)
    if header_mode == "mismatch":
        assert response.status_code == 403
        assert not route.called
    else:
        assert response.status_code == 200
        assert route.calls.last.request.headers["x-tenant-id"] == tenant


@pytest.mark.parametrize("other", ["matching", "conflicting", "malformed", "empty", "null"])
@pytest.mark.parametrize("alias", ["legacy", "plain"])
@respx.mock
def test_tenant_aliases_fail_closed(edge_app, monkeypatch, other, alias):
    from controlplane_edge.middleware import policy
    tenant = str(uuid.uuid4())
    value = {"matching": tenant, "conflicting": str(uuid.uuid4()),
             "malformed": "bad", "empty": "", "null": None}[other]
    key = "https://panopticon.dev/tenant_id" if alias == "legacy" else "tenant_id"

    async def verified(_token):
        return {"sub": "user", policy.TENANT_CLAIM: tenant, key: value}

    monkeypatch.setattr(policy, "resolve_bearer_claims", verified)
    route = respx.get("http://user.edge.test/api/v1/users").respond(200, json={})
    with TestClient(edge_app) as client:
        response = client.get("/api/v1/users", headers={"Authorization": "Bearer verified"})
    accepted = alias != "legacy" and other == "matching"
    assert response.status_code == (200 if accepted else 403)
    assert route.called == accepted


@respx.mock
def test_unbound_token_cannot_forward_caller_tenant(edge_app):
    route = respx.get("http://user.edge.test/api/v1/users").respond(200, json={})
    with TestClient(edge_app) as client:
        response = client.get("/api/v1/users", headers={
            "Authorization": f"Bearer {_fake_bearer()}",
            "X-Tenant-ID": str(uuid.uuid4()),
        })
    assert response.status_code == 200
    assert "x-tenant-id" not in route.calls.last.request.headers


@pytest.mark.parametrize(("method", "path", "status"), [
    ("GET", "/api/v1/operator/directory/users", 200),
    ("GET", "/api/v1/operator/audit", 200),
    ("GET", "/api/v1/operator/session", 200),
    ("POST", "/api/v1/operator/bans", 201),
    ("POST", "/api/v1/operator/bans/fixture/lift", 200),
    ("POST", "/api/v1/operator/users/fixture/role", 200),
    ("GET", "/api/v1/operator/audit", 403),
])
@respx.mock
def test_console_requests_reach_user_owner_with_original_authority(edge_app, method, path, status):
    upstream = respx.route(method=method, url="http://user.edge.test" + path).mock(
        return_value=httpx.Response(status, json={"owner": "user", "status": status}))
    headers = _auth_headers()
    with TestClient(edge_app) as client:
        response = client.request(method, path, headers=headers, params={"limit": 1, "offset": 2})
    assert response.status_code == status
    assert response.json() == {"owner": "user", "status": status}
    assert upstream.call_count == 1
    sent = upstream.calls.last.request
    assert sent.headers["authorization"] == headers["Authorization"]
    assert sent.headers["x-tenant-id"] == headers["X-Tenant-ID"]
    assert dict(sent.url.params) == {"limit": "1", "offset": "2"}


@respx.mock
def test_console_proxy_requires_authentication_before_owner_call(edge_app):
    upstream = respx.get("http://user.edge.test/api/v1/operator/audit").mock(
        return_value=httpx.Response(200, json={"items": []}))
    with TestClient(edge_app) as client:
        response = client.get("/api/v1/operator/audit")
    assert response.status_code == 401
    assert not upstream.called

@respx.mock
def test_sumsub_deletion_delivery_preserves_bytes_and_rejects_ambiguous_headers(edge_app):
    path = "/api/v1/verification/webhooks/sumsub/sandbox/applicant-deleted"
    route = respx.post("http://verification.edge.test" + path).mock(return_value=httpx.Response(204))
    raw = b'{ "type" : "applicantDeleted" }\n'
    headers = [("X-Payload-Digest-Alg", "HMAC_SHA256_HEX"), ("X-Payload-Digest", "1" * 64)]
    with TestClient(edge_app) as client:
        assert client.post(path, content=raw, headers=headers).status_code == 204
        sent = route.calls.last.request
        assert sent.content == raw and sent.headers["x-payload-digest"] == "1" * 64
        assert client.post(path, content=raw, headers=headers + [headers[0]]).status_code == 401
        assert client.post(path, content=b"x" * 65537, headers=headers).status_code == 413
        assert route.call_count == 1
    assert not is_public_path(path + "/", "POST")
    assert not is_public_path(path, "GET")
    assert not is_public_path(path + "/other", "POST")


@respx.mock
def test_canonical_context_discovery_preserves_verified_identity_without_tenant(edge_app,monkeypatch):
    from controlplane_edge.middleware import policy
    async def verified(token):
        assert token=='issuer-identity'
        return {'sub':'network-admin','iss':'https://issuer.example','azp':'controlplane-frontend'}
    monkeypatch.setattr(policy,'resolve_bearer_claims',verified)
    route=respx.get('http://user.edge.test/api/v1/authority/contexts').mock(return_value=httpx.Response(200,json={'tenants':[]},headers={'Cache-Control':'no-store'}))
    with TestClient(edge_app) as client:
        result=client.get('/api/v1/authority/contexts',headers={'Authorization':'Bearer issuer-identity','X-Tenant-ID':str(uuid.uuid4())})
    assert result.status_code==200
    assert route.calls.last.request.headers['authorization']=='Bearer issuer-identity'
    assert 'x-tenant-id' not in route.calls.last.request.headers
    assert result.headers['cache-control']=='no-store'


@respx.mock
def test_network_authority_reaches_user_and_private_scope_checks_stay_hidden(edge_app):
    route=respx.get('http://user.edge.test/api/v1/networks/hyperme.sh/authority').mock(return_value=httpx.Response(403,json={'detail':'Current network authority required'}))
    with TestClient(edge_app) as client:
        assert client.get('/api/v1/networks/hyperme.sh/authority',headers=_auth_headers()).status_code==403
        assert route.called
        before=len(respx.calls)
        for path in ('/api/v1/internal/network-authority/check','/api/v1/internal/organization-authority/check'):
            assert client.post(path,headers=_auth_headers(),json={}).status_code==404
        assert len(respx.calls)==before
        assert client.get('/api/v1/authority/contexts').status_code==401
