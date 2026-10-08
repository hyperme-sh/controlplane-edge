"""GET /version is unauthenticated build identity. No secrets in the body."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Match

from api.interfaces.api_controllers.version_endpoint import router, version_payload
from controlplane_edge.public_paths import is_public_path, is_versions_path
from controlplane_edge.service_versions import (
    VERSION_UPSTREAMS,
    cached_service_versions,
    collect_service_versions,
    public_version_fields,
    reset_versions_cache,
)
from controlplane_edge.service_versions import router as versions_router

SHA_A = "a" * 40
SHA_B = "b" * 40
STAMP = "2026-09-26T17:00:00Z"
DIGEST = "sha256:" + "cd" * 32

_VERSION_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "core/lib/controlplane-api/src/controlplane_api/version.py"
)
_FLEET_SOURCE = (
    Path(__file__).resolve().parents[1] / "src/controlplane_edge/service_versions.py"
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    return names


def test_version_modules_do_not_import_stripe_or_products() -> None:
    forbidden = {"stripe", "hypermesh_service", "payments_service", "aiuditor_service"}
    assert _imported_modules(_VERSION_SOURCE).isdisjoint(forbidden)
    assert _imported_modules(_FLEET_SOURCE).isdisjoint(forbidden)


def test_version_payload_reports_the_baked_sha_not_the_deploy_tag() -> None:
    body = version_payload(
        {
            "SERVICE_NAME": "controlplane-edge",
            "GIT_SHA": SHA_A,
            "PANOPTICON_IMAGE_TAG": SHA_B,
            "BUILT_AT": STAMP,
            "GITHUB_TOKEN": "ghp_secret",
            "STRIPE_SECRET_KEY": "sk_live_secret",
            "DATABASE_URL": "postgresql://user:password@db/controlplane",
        }
    )
    assert body == {
        "service": "controlplane-edge",
        "git_sha": SHA_A,
        "built_at": STAMP,
    }
    encoded = str(body)
    assert "secret" not in encoded
    assert "password" not in encoded
    assert SHA_B not in encoded


def test_version_payload_ignores_a_mutable_tag_and_omits_an_unknown_digest() -> None:
    body = version_payload(
        {
            "SERVICE_NAME": "auth-service",
            "GIT_SHA": SHA_A,
            "SOURCE_SHA": SHA_B,
            "PANOPTICON_IMAGE_TAG": "test",
            "BUILT_AT": STAMP,
            "IMAGE_DIGEST": "not-a-digest",
        }
    )
    assert body["git_sha"] == SHA_A
    assert "image_digest" not in body


def test_version_payload_reports_a_digest_when_one_was_injected() -> None:
    body = version_payload(
        {
            "SERVICE_NAME": "hypermesh-service",
            "GIT_SHA": SHA_A,
            "BUILT_AT": STAMP,
            "PANOPTICON_IMAGE_DIGEST": f"ghcr.io/fyberlabs/hypermesh-service@{DIGEST}",
        }
    )
    assert body["image_digest"] == DIGEST


def test_version_payload_unknown_when_nothing_was_baked() -> None:
    body = version_payload({"SERVICE_NAME": "not a service", "BUILT_AT": "yesterday"})
    assert body == {"service": "unknown", "git_sha": "unknown", "built_at": "unknown"}


def test_get_version_is_json_and_post_is_not_the_route() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/version")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "service" in response.json()
    assert client.post("/version").status_code == 405


@pytest.mark.parametrize(
    ("path", "method", "expected"),
    [
        ("/version", "GET", True),
        ("/version/", "GET", True),
        ("/versions", "GET", False),
        ("/versions/", "GET", False),
        ("/version", "POST", False),
        ("/versions", "POST", False),
        ("/version/admin", "GET", False),
        ("/versions/extra", "GET", False),
    ],
)
def test_version_paths_are_public_get_only(
    path: str, method: str, expected: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGE_VERSIONS_ACCESS", "authenticated")
    assert is_public_path(path, method) is expected


def test_public_version_fields_drop_anything_except_build_identity() -> None:
    reported = public_version_fields(
        {
            "service": "auth-service",
            "git_sha": SHA_A,
            "built_at": STAMP,
            "image_digest": DIGEST,
            "DATABASE_URL": "postgresql://user:password@db/controlplane",
        },
        fallback_service="auth-service",
    )
    assert reported == {
        "service": "auth-service",
        "git_sha": SHA_A,
        "built_at": STAMP,
        "image_digest": DIGEST,
    }
    leaked = public_version_fields(
        {"service": "auth-service", "git_sha": "ghp_secret", "built_at": "ok\nsecret"},
        fallback_service="auth-service",
    )
    assert leaked["git_sha"] == "unknown"
    assert "secret" not in leaked["built_at"]


@pytest.mark.asyncio
async def test_collect_versions_names_peers_and_marks_the_down_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "controlplane-edge")
    monkeypatch.setenv("GIT_SHA", SHA_A)
    monkeypatch.setenv("BUILT_AT", STAMP)
    monkeypatch.delenv("PANOPTICON_IMAGE_TAG", raising=False)

    async def fetch(url: str) -> dict:
        if url == "http://auth/version":
            return {
                "service": "auth-service",
                "git_sha": SHA_B,
                "built_at": STAMP,
                "image_digest": DIGEST,
                "token": "ghp_secret",
            }
        raise RuntimeError("connection refused")

    class Settings:
        auth_service_url = "http://auth"
        turn_service_url = "http://turn"

    body = await collect_service_versions(Settings(), fetch)
    by_name = {row["service"]: row for row in body["services"]}
    assert by_name["controlplane-edge"]["git_sha"] == SHA_A
    assert by_name["auth-service"]["image_digest"] == DIGEST
    assert "token" not in by_name["auth-service"]
    assert by_name["turn-service"] == {"service": "turn-service", "error": "unreachable"}
    assert "user-service" not in by_name
    assert len(VERSION_UPSTREAMS) == 15


def test_versions_access_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDGE_VERSIONS_ACCESS", "public")
    assert is_public_path("/versions", "GET") is True
    monkeypatch.setenv("EDGE_VERSIONS_ACCESS", "off")
    assert is_public_path("/versions", "GET") is True
    monkeypatch.setenv("EDGE_VERSIONS_ACCESS", "authenticated")
    assert is_public_path("/versions", "GET") is False
    monkeypatch.setenv("EDGE_VERSIONS_ACCESS", "nope")
    assert is_public_path("/versions", "GET") is False
    assert is_public_path("/version", "GET") is True
    assert is_versions_path("/versions", "GET") is True
    assert is_versions_path("/version", "GET") is False


def test_versions_off_does_not_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDGE_VERSIONS_ACCESS", "off")
    reset_versions_cache()
    app = FastAPI()
    app.include_router(versions_router)
    response = TestClient(app).get("/versions")
    assert response.status_code == 404
    assert response.json()["detail"] == "versions is disabled"


@pytest.mark.asyncio
async def test_versions_cache_serves_one_fanout_until_the_ttl() -> None:
    reset_versions_cache()
    calls = {"n": 0}
    clock = {"now": 0.0}

    async def loader():
        calls["n"] += 1
        return {"services": [{"service": "controlplane-edge", "git_sha": SHA_A}]}

    first = await cached_service_versions(loader, now=lambda: clock["now"], ttl=20)
    second = await cached_service_versions(loader, now=lambda: clock["now"] + 19, ttl=20)
    assert first == second
    assert calls["n"] == 1
    clock["now"] = 20
    await cached_service_versions(loader, now=lambda: clock["now"], ttl=20)
    assert calls["n"] == 2
    reset_versions_cache()


@pytest.mark.asyncio
async def test_versions_cache_single_flight() -> None:
    reset_versions_cache()
    calls = {"n": 0}
    started = asyncio.Event()
    release = asyncio.Event()

    async def loader():
        calls["n"] += 1
        started.set()
        await release.wait()
        return {"services": []}

    first = asyncio.create_task(cached_service_versions(loader, ttl=20))
    await started.wait()
    second = asyncio.create_task(cached_service_versions(loader, ttl=20))
    await asyncio.sleep(0)
    release.set()
    assert await first == await second
    assert calls["n"] == 1
    reset_versions_cache()


def test_versions_stays_behind_the_rate_limiter_when_public(monkeypatch: pytest.MonkeyPatch) -> None:
    from controlplane_edge.middleware.rate_limit import GatewayRateLimitMiddleware

    monkeypatch.setenv("EDGE_VERSIONS_ACCESS", "public")

    class Limiter:
        def __init__(self) -> None:
            self.calls = 0

        def allow(self, tenant_id, user_sub) -> bool:
            del tenant_id, user_sub
            self.calls += 1
            return True

    app = FastAPI()
    app.add_middleware(GatewayRateLimitMiddleware)

    @app.get("/versions")
    def versions() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/version")
    def version() -> dict[str, bool]:
        return {"ok": True}

    limiter = Limiter()
    app.state.gateway_rate_limiter = limiter
    client = TestClient(app)
    assert client.get("/versions").status_code == 200
    assert client.get("/version").status_code == 200
    assert limiter.calls == 1


def test_machine_identity_exchanges_stay_behind_the_rate_limiter() -> None:
    from controlplane_edge.middleware.rate_limit import GatewayRateLimitMiddleware

    class Limiter:
        def __init__(self) -> None:
            self.calls = 0

        def allow(self, tenant_id, user_sub) -> bool:
            del tenant_id, user_sub
            self.calls += 1
            return self.calls <= 4

    app = FastAPI()
    app.add_middleware(GatewayRateLimitMiddleware)
    paths = (
        "/api/v1/aiuditor/machine/renew",
        "/api/v1/hypermesh/agent/identity/bind",
        "/api/v1/hypermesh/agent/identity/token",
        "/api/v1/hypermesh/agent/identity/contract-token",
    )
    for path in paths:
        app.add_api_route(path, lambda: {"ok": True}, methods=["POST"])

    @app.get("/version")
    def version() -> dict[str, bool]:
        return {"ok": True}

    limiter = Limiter()
    app.state.gateway_rate_limiter = limiter
    client = TestClient(app)
    assert [client.post(path).status_code for path in paths] == [200] * 4
    assert client.post(paths[0]).status_code == 429
    assert client.get("/version").status_code == 200
    assert limiter.calls == 5


def test_monolith_serves_version_ahead_of_the_catch_all() -> None:
    from api import app

    def first_full(path: str) -> str | None:
        scope = {
            "type": "http",
            "path": path,
            "method": "GET",
            "headers": [],
            "query_string": b"",
            "root_path": "",
        }
        for route in app.routes:
            match, _ = route.matches(scope)
            if match == Match.FULL:
                return getattr(route, "path", None)
        return None

    assert first_full("/version") == "/version"
    assert first_full("/versions") == "/versions"
