"""Unified JWT + API key + tenant extraction for REST and GraphQL (request.state)."""

from __future__ import annotations

import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from api.infrastructure.security.api_key_exchange_jwt import mint_api_key_session_jwt
from controlplane_edge.api_keys_client import validate_api_key_remote
from controlplane_edge.auth_utils import resolve_bearer_claims
from controlplane_edge.host_setup_auth import resolve_setup_claims
from controlplane_edge.edge_settings import GatewayCrossCuttingSettings
from controlplane_edge.public_paths import is_public_path

SITE_TOKEN_HEAD = "hm_site_"


def looks_like_site_machine_token(raw: str) -> bool:
    """Opaque Panopticon site token. Not a JWT — hypermesh-service verifies."""

    return raw.startswith(SITE_TOKEN_HEAD) and len(raw) > len(SITE_TOKEN_HEAD)


TENANT_CLAIM = "https://panopticon.dev/tenant_id"


def _tenant_from_claims(claims: dict[str, Any] | None) -> uuid.UUID | None:
    if not claims:
        return None
    raw = claims.get(TENANT_CLAIM) or claims.get("tenant_id")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


class GatewayAuthMiddleware(BaseHTTPMiddleware):
    """Populate ``request.state.jwt_claims``, ``tenant_id``, ``user_sub``; enforce auth on protected routes."""

    def __init__(self, app, settings: GatewayCrossCuttingSettings | None = None) -> None:
        super().__init__(app)
        self._settings = settings or GatewayCrossCuttingSettings()

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        auth_header = request.headers.get("Authorization")
        bearer: str | None = None
        if auth_header and auth_header.startswith("Bearer "):
            bearer = auth_header[7:].strip()

        tid_raw = request.headers.get("x-tenant-id") or request.headers.get("X-Tenant-ID")
        tenant_id: uuid.UUID | None = None
        if tid_raw:
            try:
                tenant_id = uuid.UUID(str(tid_raw).strip())
            except ValueError:
                tenant_id = None

        api_key_header = request.headers.get("x-api-key") or request.headers.get("X-Api-Key")

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
                        content={"detail": "X-Tenant-ID is required when using X-Api-Key"},
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

        claimed = _tenant_from_claims(claims)
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

        if is_public_path(path, request.method):
            return await call_next(request)

        if claims is None and bearer and looks_like_site_machine_token(bearer):
            return await call_next(request)

        if claims is None and bearer:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing JWT claims"},
            )
        if claims is None and not bearer:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization Bearer token or valid X-Api-Key required"},
            )

        return await call_next(request)
