"""Gateway rate limiting (tenant + user sub, or anonymous bucket)."""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from controlplane_edge.rate_limiter import TenantUserRateLimiter
from controlplane_edge.public_paths import (
    is_issuer_session_end_path,
    is_machine_identity_path,
    is_public_path,
    is_sumsub_webhook_path,
    is_versions_path,
    is_witness_policy_path,
    is_contact_lane_path,
)


_ANON_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000000")


class GatewayRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        # /versions fans out to every upstream. It stays on this limiter even
        # when EDGE_VERSIONS_ACCESS=public lets it skip the session JWT.
        # Machine-proof exchanges and the issuer-session fence accept
        # unauthenticated input that reaches a service, so they stay on the
        # anonymous (client address) bucket.
        if (
            is_public_path(path, request.method)
            and not is_versions_path(path, request.method)
            and not is_machine_identity_path(path, request.method)
            and not is_issuer_session_end_path(path, request.method)
            and not is_sumsub_webhook_path(path, request.method)
            and not is_witness_policy_path(path, request.method)
            and not is_contact_lane_path(path, request.method)
        ):
            return await call_next(request)

        lim: TenantUserRateLimiter | None = getattr(request.app.state, "gateway_rate_limiter", None)
        if lim is None:
            return await call_next(request)

        if (
            is_machine_identity_path(path, request.method)
            or is_issuer_session_end_path(path, request.method)
            or is_sumsub_webhook_path(path, request.method)
            or is_witness_policy_path(path, request.method)
            or is_contact_lane_path(path, request.method)
        ):
            # The tenant header on these routes is unauthenticated; one bucket
            # per client address, so rotating tenant IDs gains nothing.
            tenant_id = _ANON_TENANT
            user_sub = request.client.host if request.client else "unknown"
        else:
            tenant_id = getattr(request.state, "tenant_id", None) or _ANON_TENANT
            user_sub = getattr(request.state, "user_sub", None) or request.client.host if request.client else "unknown"

        if not lim.allow(tenant_id, str(user_sub)):
            return JSONResponse(status_code=429, content={"detail": "Gateway rate limit exceeded"})

        return await call_next(request)
