"""Unauthenticated GET Hypermesh catalog/classes; lease/chat stay protected."""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from controlplane_edge.public_paths import is_public_path
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting


def _fake_bearer(sub: str = "11111111-1111-1111-1111-111111111111") -> str:
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


@pytest.fixture
def browse_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("CPEDGE_HYPERMESH_SERVICE_URL", "http://hm.browse.test")
    monkeypatch.setenv("CPEDGE_HYPERMESH_GATEWAY_SERVICE_URL", "http://hmr.browse.test")
    monkeypatch.setenv("CPEDGE_RATE_LIMIT_PER_MINUTE", "5000")
    import api.core.config as api_config

    monkeypatch.setattr(api_config.settings, "keycloak_jwks_url", None)
    monkeypatch.setattr(api_config.settings, "keycloak_issuer", None)

    app = FastAPI(title="Gateway browse")
    register_gateway_cross_cutting(app)
    return app


def test_hypermesh_browse_is_public_get_only() -> None:
    assert is_public_path("/api/v1/hypermesh/catalog", "GET") is True
    assert is_public_path("/api/v1/hypermesh/classes", "GET") is True
    assert is_public_path("/api/v1/hypermesh/nodes", "GET") is True
    assert is_public_path("/api/v1/hypermesh/ready", "GET") is True
    assert is_public_path("/api/v1/hypermesh/ready/", "GET") is True
    assert is_public_path("/api/v1/hypermesh/ready", "POST") is False
    assert is_public_path("/api/v1/hypermesh/catalog/", "GET") is True
    assert is_public_path("/api/v1/hypermesh/classes/", "GET") is True
    assert is_public_path("/api/v1/hypermesh/nodes/", "GET") is True
    assert is_public_path("/api/v1/hypermesh/catalog", "POST") is False
    assert is_public_path("/api/v1/hypermesh/classes", "POST") is False
    assert is_public_path("/api/v1/hypermesh/nodes", "POST") is False
    assert is_public_path("/api/v1/hypermesh/leases", "GET") is False
    assert is_public_path("/api/v1/hypermesh/leases", "POST") is False
    assert is_public_path("/api/v1/hypermesh/renter/hosts", "GET") is False
    assert is_public_path("/api/v1/hypermesh/renter/chat/completions", "POST") is False
    assert is_public_path("/api/v1/hypermesh-gateway/v1/chat/completions", "POST") is False
    assert is_public_path("/api/v1/hypermesh-gateway/v1/ir/chat/completions", "POST") is False
    assert is_public_path("/api/v1/hypermesh-gateway/v1/ir/receipts", "GET") is False
    assert is_public_path("/api/v1/aiuditor/connections", "GET") is False
    assert is_public_path("/api/v1/aiuditor/connections", "POST") is False
    assert is_public_path("/api/v1/hypermesh/devices", "GET") is False
    assert is_public_path(
        "/api/v1/hypermesh/devices/a6400000-0640-4000-8000-000000000001/path-b/runs",
        "GET",
    ) is False
    assert is_public_path(
        "/api/v1/hypermesh/path-b/runs/a6400000-0640-4000-8000-000000000001",
        "GET",
    ) is False
    assert is_public_path("/api/v1/hypermesh/internal/gateways", "POST") is False
    # Host enroll is a separate allowlist (POST only). Browse GET rules stay GET-only.
    assert is_public_path("/api/v1/hypermesh/agent/enroll", "GET") is False


def test_openapi_lists_public_hypermesh_browse_paths(browse_app: FastAPI) -> None:
    with TestClient(browse_app) as client:
        spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/v1/hypermesh/catalog" in paths
    assert "/api/v1/hypermesh/classes" in paths
    assert "/api/v1/hypermesh/nodes" in paths
    assert "get" in paths["/api/v1/hypermesh/catalog"]
    assert "get" in paths["/api/v1/hypermesh/classes"]
    assert "get" in paths["/api/v1/hypermesh/nodes"]
    assert "post" not in paths["/api/v1/hypermesh/catalog"]
    catalog_op = paths["/api/v1/hypermesh/catalog"]["get"]
    classes_op = paths["/api/v1/hypermesh/classes"]["get"]
    nodes_op = paths["/api/v1/hypermesh/nodes"]["get"]
    assert catalog_op.get("security") == []
    assert classes_op.get("security") == []
    assert nodes_op.get("security") == []
    catalog_text = f"{catalog_op.get('summary')} {catalog_op.get('description')}".lower()
    classes_text = f"{classes_op.get('summary')} {classes_op.get('description')}".lower()
    assert "hypermesh" in catalog_text
    assert "hyperme.sh" in catalog_text
    assert "public_sku" in catalog_text
    assert "hypermesh" in classes_text
    assert "public_sku" in classes_text
    assert "thor" in classes_text
    assert "/api/v1/tw" not in spec["paths"]


@respx.mock
def test_unauthenticated_catalog_and_classes_are_proxied(browse_app: FastAPI) -> None:
    catalog_body = [
        {
            "id": "llama-3.1-8b-q4",
            "artifact_name": "Llama 3.1 8B Instruct Q4_K_M",
            "class_id": "agx-large",
            "certified": False,
            "public_sku": True,
        }
    ]
    classes_body = [
        {"id": "nx-volume", "public_sku": True},
        {"id": "agx-large", "public_sku": True},
    ]
    respx.get("http://hm.browse.test/api/v1/hypermesh/catalog").mock(
        return_value=httpx.Response(200, json=catalog_body)
    )
    respx.get("http://hm.browse.test/api/v1/hypermesh/classes").mock(
        return_value=httpx.Response(200, json=classes_body)
    )
    nodes_body = [
        {
            "public_label": "agx-large-a6400000",
            "class_id": "agx-large",
            "certified": True,
            "online": True,
            "selling": True,
        }
    ]
    respx.get("http://hm.browse.test/api/v1/hypermesh/nodes").mock(
        return_value=httpx.Response(200, json=nodes_body)
    )
    with TestClient(browse_app) as client:
        catalog = client.get(
            "/api/v1/hypermesh/catalog",
            headers={"Origin": "https://hyperme.sh"},
        )
        classes = client.get(
            "/api/v1/hypermesh/classes",
            headers={"Origin": "https://hyperme.sh"},
        )
        nodes = client.get(
            "/api/v1/hypermesh/nodes",
            headers={"Origin": "https://hyperme.sh"},
        )
    assert catalog.status_code == 200, catalog.text
    assert classes.status_code == 200, classes.text
    assert nodes.status_code == 200, nodes.text
    assert catalog.json()[0]["id"] == "llama-3.1-8b-q4"
    assert all(row["public_sku"] is True for row in classes.json())
    assert {row["id"] for row in classes.json()} == {"nx-volume", "agx-large"}
    assert all(row["id"] != "thor" for row in classes.json())
    assert nodes.json()[0]["public_label"] == "agx-large-a6400000"
    assert "device_id" not in nodes.json()[0]


@respx.mock
def test_checkout_lease_and_chat_still_require_auth(browse_app: FastAPI) -> None:
    with TestClient(browse_app) as client:
        checkout = client.post(
            "/api/v1/hypermesh/leases",
            json={
                "kind": "p2_loaded_model",
                "catalog_id": "llama-3.1-8b-q4",
                "renter_user_id": "11111111-1111-1111-1111-111111111111",
                "success_url": "https://hyperme.sh/ok",
                "cancel_url": "https://hyperme.sh/no",
            },
        )
        leases = client.get("/api/v1/hypermesh/leases")
        hosts = client.get("/api/v1/hypermesh/renter/hosts")
        renter_chat = client.post(
            "/api/v1/hypermesh/renter/chat/completions",
            json={"lease_id": str(uuid.uuid4()), "messages": []},
        )
        router_chat = client.post(
            "/api/v1/hypermesh-gateway/v1/chat/completions",
            json={"lease_id": str(uuid.uuid4()), "messages": []},
        )
    assert checkout.status_code == 401
    assert leases.status_code == 401
    assert hosts.status_code == 401
    assert renter_chat.status_code == 401
    assert router_chat.status_code == 401
    assert checkout.json()["detail"] == "Authorization Bearer token or valid X-Api-Key required"


@respx.mock
def test_authenticated_lease_is_still_proxied(browse_app: FastAPI) -> None:
    respx.post("http://hm.browse.test/api/v1/hypermesh/leases").mock(
        return_value=httpx.Response(201, json={"id": str(uuid.uuid4()), "status": "offered"})
    )
    headers = {
        "Authorization": f"Bearer {_fake_bearer()}",
        "X-Tenant-ID": str(uuid.uuid4()),
    }
    with TestClient(browse_app) as client:
        offered = client.post(
            "/api/v1/hypermesh/leases",
            headers=headers,
            json={
                "kind": "p2_loaded_model",
                "catalog_id": "llama-3.1-8b-q4",
                "renter_user_id": "11111111-1111-1111-1111-111111111111",
                "success_url": "https://hyperme.sh/ok",
                "cancel_url": "https://hyperme.sh/no",
            },
        )
    assert offered.status_code == 201
    assert offered.json()["status"] == "offered"


def test_pricing_transparency_is_exact_public_get(browse_app: FastAPI) -> None:
    path = "/api/v1/hypermesh/pricing/transparency"
    assert is_public_path(path, "GET")
    assert is_public_path(path + "/", "GET")
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        assert not is_public_path(path, method)
    assert not is_public_path(path + "/private", "GET")
    assert not is_public_path("/api/v1/hypermesh/pricing", "GET")
    with TestClient(browse_app) as client:
        operation = client.get("/openapi.json").json()["paths"][path]["get"]
    assert operation["security"] == []


@respx.mock
def test_public_pricing_transparency_is_proxied(browse_app: FastAPI) -> None:
    path = "/api/v1/hypermesh/pricing/transparency"
    body = {"ruleset": {"version": "EXAMPLE", "active": True,
                        "public_summary": ["EXAMPLE rules"]}, "pools": []}
    upstream = respx.get("http://hm.browse.test" + path).mock(
        return_value=httpx.Response(200, json=body)
    )
    with TestClient(browse_app) as client:
        response = client.get(path, headers={"Origin": "https://hyperme.sh"})
    assert response.status_code == 200
    assert response.json() == body
    assert upstream.called

def test_bootstrap_public_paths_are_exact_and_read_only():
    base = "/api/v1/hypermesh/public/host-releases"
    for path in (base + "/test", base + "/prod", base + "/test/12-aaaaaaaaaaaa/checksums.txt.sig",
                 base + "/prod/1.2.3/hypermesh-deploy_1.2.3_linux_arm64",
                 base + "/test/12-aaaaaaaaaaaa/platforms.json",
                 base + "/test/12-aaaaaaaaaaaa/hypermesh-deploy_0.0.12_darwin_arm64",
                 base + "/test/12-aaaaaaaaaaaa/hypermesh-agent_0.0.12_darwin_arm64"):
        assert is_public_path(path, "GET")
        assert not is_public_path(path, "POST")
    for path in (base + "/other", base + "/test/12-aaaaaaaaaaaa/private.key",
                 base + "/test/12-aaaaaaaaaaaa/releaseXjson", base + "/test/../../agent",
                 base + "/test/12-aaaaaaaaaaaa/hypermesh-deploy_0.0.12_darwin_amd64",
                 base + "/test/12-aaaaaaaaaaaa/hypermesh-deploy_0.0.12_windows_arm64"):
        assert not is_public_path(path, "GET")

@pytest.mark.parametrize("artifact", ["checksums.txt", "platforms.json",
    "hypermesh-deploy_0.0.12_linux_arm64", "hypermesh-deploy_0.0.12_linux_amd64",
    "hypermesh-deploy_0.0.12_darwin_arm64", "hypermesh-agent_0.0.12_darwin_arm64"])
@respx.mock
def test_public_installer_redirect_survives_gateway(browse_app, artifact):
    path = "/api/v1/hypermesh/public/host-releases/test/12-aaaaaaaaaaaa/" + artifact
    destination = "https://updates.example.invalid/test/checksums.txt?sp=r&sig=example"
    respx.get("http://hm.browse.test" + path).mock(return_value=httpx.Response(
        307, headers={"Location": destination, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}))
    with TestClient(browse_app, follow_redirects=False) as client:
        response = client.get(path)
    assert response.status_code == 307
    assert response.headers["location"] == destination
    assert response.headers["cache-control"] == "no-store"
