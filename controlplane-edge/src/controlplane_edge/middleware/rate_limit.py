"""Gateway rate limiting (tenant + user sub, or anonymous bucket)."""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from api.infrastructure.tenant_user_rate_limiter import TenantUserRateLimiter
from controlplane_edge.public_paths import is_public_path


_ANON_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000000")


class GatewayRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if is_public_path(path, request.method):
            return await call_next(request)

        lim: TenantUserRateLimiter | None = getattr(request.app.state, "gateway_rate_limiter", None)
        if lim is None:
            return await call_next(request)

        tenant_id = getattr(request.state, "tenant_id", None) or _ANON_TENANT
        user_sub = getattr(request.state, "user_sub", None) or request.client.host if request.client else "unknown"

        if not lim.allow(tenant_id, str(user_sub)):
            return JSONResponse(status_code=429, content={"detail": "Gateway rate limit exceeded"})

        return await call_next(request)
