"""Edge view of every service's /version.

The public edge is the only host the freshness check can reach. Each
upstream already has a base URL for OpenAPI aggregation; this module GETs
``/version`` on those URLs and returns the same build-identity fields.
It does not import product packages.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.interfaces.api_controllers.version_endpoint import version_payload
from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SERVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_STAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")

router = APIRouter()

# Compose service name, then the settings attribute that holds its base URL.
# controlplane-edge is added by the handler from this process. One-shot
# containers (controlplane-migrate, known-host enroll) are not HTTP servers.
VERSION_UPSTREAMS: tuple[tuple[str, str], ...] = (
    ("auth-service", "auth_service_url"),
    ("user-service", "user_service_url"),
    ("payment-service", "payment_service_url"),
    ("acl-service", "acl_service_url"),
    ("marketplace", "marketplace_service_url"),
    ("ai-service", "ai_service_url"),
    ("api-keys-service", "api_keys_service_url"),
    ("template-service", "template_service_url"),
    ("tennessee-windage-service", "tennessee_windage_service_url"),
    ("hypermesh-service", "hypermesh_service_url"),
    ("hypermesh-gateway", "hypermesh_gateway_service_url"),
    ("aiuditor-service", "aiuditor_service_url"),
    ("turn-service", "turn_service_url"),
    ("oracles-service", "oracles_service_url"),
    ("payments-service", "payments_service_url"),
)

FetchVersion = Callable[[str], Awaitable[Mapping[str, Any]]]

_PROBE_TIMEOUT_S = 2.0


def public_version_fields(body: Mapping[str, Any], *, fallback_service: str) -> dict[str, str]:
    """Copy only build-identity fields. Drop anything else an upstream sent."""

    raw_service = body.get("service")
    if isinstance(raw_service, str) and _SERVICE.fullmatch(raw_service.strip()):
        service = raw_service.strip()
    elif _SERVICE.fullmatch(fallback_service):
        service = fallback_service
    else:
        service = "unknown"
    raw_sha = body.get("git_sha")
    git_sha = raw_sha.strip().lower() if isinstance(raw_sha, str) else ""
    if not _GIT_SHA.fullmatch(git_sha):
        git_sha = "unknown"
    raw_built = body.get("built_at")
    built_at = raw_built.strip() if isinstance(raw_built, str) else ""
    if not _STAMP.fullmatch(built_at):
        built_at = "unknown"
    reported: dict[str, str] = {
        "service": service,
        "git_sha": git_sha,
        "built_at": built_at,
    }
    digest = body.get("image_digest")
    if isinstance(digest, str):
        match = _DIGEST.search(digest.strip().lower())
        if match is not None:
            reported["image_digest"] = match.group(0)
    return reported


async def collect_service_versions(
    settings: Any,
    fetch: FetchVersion,
) -> dict[str, list[dict[str, str]]]:
    """This process, then each configured upstream. Unset URLs are omitted."""

    rows: list[dict[str, str]] = [version_payload()]

    async def one(name: str, base: object) -> dict[str, str] | None:
        if base is None or not str(base).strip():
            return None
        url = str(base).rstrip("/") + "/version"
        try:
            body = await fetch(url)
        except Exception:
            return {"service": name, "error": "unreachable"}
        if not isinstance(body, Mapping):
            return {"service": name, "error": "unreachable"}
        return public_version_fields(body, fallback_service=name)

    peers = await asyncio.gather(
        *(one(name, getattr(settings, attr, None)) for name, attr in VERSION_UPSTREAMS)
    )
    for peer in peers:
        if peer is not None:
            rows.append(peer)
    return {"services": rows}


@router.get("/versions")
async def versions() -> JSONResponse:
    settings = OpenAPIAggregationSettings()
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:

        async def fetch(url: str) -> Mapping[str, Any]:
            response = await client.get(url)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, Mapping):
                raise ValueError("version payload was not an object")
            return body

        payload = await collect_service_versions(settings, fetch)
    return JSONResponse(payload)
