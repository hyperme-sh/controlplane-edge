"""Unified JWT + API key + tenant extraction for REST and GraphQL (request.state)."""

from __future__ import annotations

import uuid
import re
from typing import Any

from controlplane_identity.internal_token import request_has_internal_token
from controlplane_identity.security.api_key_exchange_jwt import mint_api_key_session_jwt
from controlplane_api.config import settings as api_settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from controlplane_edge.api_keys_client import validate_api_key_remote
from controlplane_edge.auth_utils import resolve_bearer_claims
from controlplane_edge.closure_auth import closure_claims, closure_route
from controlplane_edge.edge_settings import GatewayCrossCuttingSettings
from controlplane_edge.host_setup_auth import resolve_setup_claims
from controlplane_edge.public_paths import is_public_path, is_contact_lane_path

SITE_TOKEN_HEAD = "hm_site_"


def looks_like_site_machine_token(raw: str) -> bool:
    """Opaque spanopticon site token. Not a JWT — hypermesh-service verifies."""

    return raw.startswith(SITE_TOKEN_HEAD) and len(raw) > len(SITE_TOKEN_HEAD)


_SITE_ID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_SITE_ROUTES = {
    "POST": (
        r"/api/v1/hypermesh/site/jobs",
        r"/api/v1/auditor/v0/tickets",
        rf"/api/v1/auditor/v0/tickets/{_SITE_ID}/ack",
        r"/api/v1/grants/v0/grants",
    ),
    "GET": (
        rf"/api/v1/hypermesh/site/jobs/{_SITE_ID}",
        rf"/api/v1/hypermesh/site/devices/{_SITE_ID}",
        rf"/api/v1/auditor/v0/tickets/{_SITE_ID}",
        r"/api/v1/grants/v0/grants",
        rf"/api/v1/grants/v0/grants/{_SITE_ID}",
    ),
}


def site_token_route(path: str, method: str) -> bool:
    """Only routes whose owning upstream validates opaque site credentials."""
    return any(re.fullmatch(pattern, path) for pattern in _SITE_ROUTES.get(method, ()))


TENANT_CLAIM = "https://spanopticon.dev/tenant_id"
_RETIRED_TENANT_CLAIM = "https://panopticon.dev/tenant_id"


def _tenant_from_claims(claims: dict[str, Any] | None) -> uuid.UUID | None:
    if not claims:
        return None
    if _RETIRED_TENANT_CLAIM in claims:
        raise ValueError("Retired tenant claim; reauthenticate with the current issuer")
    # All current tenant aliases must agree.
    tenants = {
        uuid.UUID(str(claims[key]))
        for key in (TENANT_CLAIM, "tenant_id")
        if key in claims
    }
    if len(tenants) > 1:
        raise ValueError("Conflicting token tenants")
    return next(iter(tenants), None)


class GatewayAuthMiddleware(BaseHTTPMiddleware):
    """Populate ``request.state.jwt_claims``, ``tenant_id``, ``user_sub``; enforce auth on protected routes."""

    def __init__(
        self, app, settings: GatewayCrossCuttingSettings | None = None
    ) -> None:
        super().__init__(app)
        self._settings = settings or GatewayCrossCuttingSettings()
        from controlplane_edge.lane_access_log import install_lane_log_filter
        install_lane_log_filter()

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path.startswith("/api/v1/internal/") or "/internal/account-lifecycle" in request.url.path:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if is_contact_lane_path(path, request.method):
            # Lane possession is a transport capability, not an account lookup.
            request.state.jwt_claims = None
            request.state.tenant_id = None
            request.state.user_sub = None
            request.state.bearer_token = None
            return await call_next(request)
        if "Authorization" in request.headers and "X-Api-Key" in request.headers:
            return JSONResponse(
                status_code=401,
                content={"detail": "Send either Authorization or X-Api-Key, not both"},
            )
        auth_header = request.headers.get("Authorization")
        bearer: str | None = None
        if auth_header and auth_header.startswith("Bearer "):
            bearer = auth_header[7:].strip()

        if closure_route(path, request.method):
            claims = await closure_claims(bearer, path) if bearer else None
            if claims is None:
                return JSONResponse(status_code=401, content={"detail": "Native account authority required"})
            request.state.jwt_claims = claims
            request.state.bearer_token = bearer
            request.state.user_sub = claims["sub"]
            request.state.tenant_id = None
            return await call_next(request)

        tid_raw = request.headers.get("x-tenant-id") or request.headers.get(
            "X-Tenant-ID"
        )
        tenant_id: uuid.UUID | None = None
        if tid_raw:
            try:
                tenant_id = uuid.UUID(str(tid_raw).strip())
            except ValueError:
                tenant_id = None

        api_key_header = request.headers.get("x-api-key") or request.headers.get(
            "X-Api-Key"
        )

        claims: dict[str, Any] | None = None
        user_sub: str | None = None

        if bearer:
            claims = await resolve_setup_claims(bearer, path, request.method)
            if claims is None:
                claims = await resolve_bearer_claims(bearer)
            if claims is not None:
                user_sub = str(claims.get("sub") or "") or None

        if claims is None and api_key_header and self._settings.api_keys_service_url:
            if tenant_id is None:
                if not is_public_path(path, request.method):
                    return JSONResponse(
                        status_code=400,
                        content={
                            "detail": "X-Tenant-ID is required when using X-Api-Key"
                        },
                    )
            else:
                tracker = getattr(request.app.state, "api_key_failure_tracker", None)
                client_ip = request.client.host if request.client else "unknown"
                if tracker is not None and tracker.is_blocked(client_ip):
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Too many invalid API key attempts"},
                    )
                data = await validate_api_key_remote(
                    base_url=self._settings.api_keys_service_url,
                    api_key=api_key_header.strip(),
                    tenant_id=tenant_id,
                )
                if data is None:
                    if tracker is not None:
                        tracker.record_failure(client_ip)
                    if not is_public_path(path, request.method):
                        return JSONResponse(
                            status_code=401,
                            content={"detail": "Invalid API key"},
                        )
                else:
                    kid = uuid.UUID(str(data["key_id"]))
                    scopes_raw = data.get("scopes") or []
                    scopes = [str(s) for s in scopes_raw]
                    tid_u = uuid.UUID(str(data["tenant_id"]))
                    minted = mint_api_key_session_jwt(
                        key_record_id=kid,
                        tenant_id=tid_u,
                        scopes=scopes,
                        purpose=str(data.get("purpose") or "") or None,
                    )
                    bearer = minted
                    claims = await resolve_bearer_claims(minted)
                    if claims is not None:
                        user_sub = str(claims.get("sub") or "") or None

        try:
            claimed = _tenant_from_claims(claims)
        except (ValueError, AttributeError, TypeError):
            return JSONResponse(
                status_code=403, content={"detail": "Invalid or conflicting token tenant"}
            )
        if claimed is not None:
            if tenant_id is not None and tenant_id != claimed:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "X-Tenant-ID must match token tenant"},
                )
            tenant_id = claimed
        elif claims is not None:
            # Bound session/exchange JWTs carry tenant. A raw Keycloak (or
            # other) JWT must not bind X-Tenant-ID — switch-tenant first.
            tenant_id = None

        request.state.jwt_claims = claims
        request.state.bearer_token = bearer
        request.state.tenant_id = tenant_id
        request.state.user_sub = user_sub

        # Payment's current-owner read uses the existing internal credential,
        # not a human session. Keep this exact method/path credential-gated at
        # the edge; Hypermesh independently verifies it and current ownership.
        # This remains a protected path for rate limiting and all other callers.
        if (
            request.method == "POST"
            and path.rstrip("/") == "/api/v1/hypermesh/host-management/ownership"
            and tenant_id is not None
            and request_has_internal_token(
                request, api_settings.hypermesh_internal_token
            )
        ):
            return await call_next(request)

        if is_public_path(path, request.method):
            return await call_next(request)

        if (claims is None and bearer and looks_like_site_machine_token(bearer)
                and self._settings.edge_proxy_enabled
                and site_token_route(path, request.method)):
            return await call_next(request)

        if claims is None and bearer:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing JWT claims"},
            )
        if claims is None and not bearer:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authorization Bearer token or valid X-Api-Key required"
                },
            )

        return await call_next(request)
