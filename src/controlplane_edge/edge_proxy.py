"""Mount-less HTTP reverse proxy from the gateway to extracted services."""

from __future__ import annotations

import logging
from http.cookiejar import CookieJar, DefaultCookiePolicy

import httpx
from fastapi import FastAPI
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
from controlplane_edge.edge_routes import (
    EDGE_ROUTES,
    locked_monolith_checkout_path,
    match_edge_route,
)
from controlplane_edge.edge_settings import GatewayCrossCuttingSettings

logger = logging.getLogger(__name__)

_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)

_STRIP_RESPONSE = frozenset(
    {
        "content-encoding",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
    }
)


class _RejectCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False


def _proxy_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, cookies=CookieJar(policy=_RejectCookies()))


def _forward_request_headers(request: Request) -> dict[str, str]:
    """Copy inbound headers; prefer the gateway-minted bearer when present."""

    out: dict[str, str] = {}
    for key, value in request.headers.items():
        lk = key.lower()
        if lk in _HOP_BY_HOP or lk == "authorization":
            continue
        out[key] = value

    bearer = getattr(request.state, "bearer_token", None)
    if bearer:
        out["Authorization"] = f"Bearer {bearer}"
    elif request.headers.get("authorization"):
        out["Authorization"] = request.headers["authorization"]

    client_host = request.client.host if request.client else None
    if client_host:
        prior = request.headers.get("x-forwarded-for")
        out["X-Forwarded-For"] = f"{prior}, {client_host}" if prior else client_host
    out.setdefault("X-Forwarded-Proto", request.url.scheme)
    if request.url.hostname:
        out.setdefault("X-Forwarded-Host", request.url.hostname)
    return out


class EdgeProxyMiddleware(BaseHTTPMiddleware):
    """Forward matched prefixes to extracted services; leave monolith routes alone."""

    def __init__(
        self,
        app,
        *,
        settings: OpenAPIAggregationSettings | None = None,
        cross: GatewayCrossCuttingSettings | None = None,
    ) -> None:
        super().__init__(app)
        self._settings = settings or OpenAPIAggregationSettings()
        self._cross = cross or GatewayCrossCuttingSettings()

    async def dispatch(self, request: Request, call_next) -> Response:
        if locked_monolith_checkout_path(request.url.path):
            return JSONResponse(
                status_code=410,
                content={
                    "detail": (
                        "Card checkout is gone. Leases are paid in USDC "
                        "through /api/v1/payments/usdc/lease-payments"
                    ),
                },
            )
        if not self._cross.edge_proxy_enabled:
            return await call_next(request)

        match = match_edge_route(request.url.path, self._settings)
        if match is None:
            return await call_next(request)

        if not match.base_url:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "upstream not configured",
                    "service": match.service_id,
                },
            )

        target = match.base_url + request.url.path
        if request.url.query:
            target = f"{target}?{request.url.query}"

        body = await request.body()
        timeout = httpx.Timeout(self._cross.proxy_timeout_s)
        client = getattr(request.app.state, "edge_proxy_client", None)
        own_client = False
        if client is None:
            client = _proxy_client(timeout)
            own_client = True

        # Streamed, so token-by-token chat completions reach the caller as they
        # are produced instead of being held until the upstream is done.
        upstream_request = httpx.Request(
            request.method,
            target,
            headers=_forward_request_headers(request),
            content=body,
            extensions={"timeout": timeout.as_dict()},
        )
        try:
            upstream = await client.send(upstream_request, stream=True, follow_redirects=False)
        except httpx.HTTPError as exc:
            logger.warning(
                "edge proxy upstream error service=%s: %s",
                match.service_id,
                exc,
            )
            if own_client:
                await client.aclose()
            return JSONResponse(
                status_code=502,
                content={
                    "detail": "upstream unreachable",
                    "service": match.service_id,
                },
            )

        headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in _STRIP_RESPONSE
        }

        async def _release() -> None:
            await upstream.aclose()
            if own_client:
                await client.aclose()

        return StreamingResponse(
            # Decoded, because content-encoding is stripped from the response.
            upstream.aiter_bytes(),
            status_code=upstream.status_code,
            headers=headers,
            background=BackgroundTask(_release),
        )


def register_edge_proxy(app: FastAPI) -> None:
    """Install the edge proxy as the innermost gateway middleware."""

    settings = OpenAPIAggregationSettings()
    cross = GatewayCrossCuttingSettings()
    timeout = httpx.Timeout(cross.proxy_timeout_s)
    app.state.edge_proxy_client = _proxy_client(timeout)
    app.add_middleware(EdgeProxyMiddleware, settings=settings, cross=cross)
    logger.info(
        "Gateway edge proxy registered (enabled=%s, routes=%s)",
        cross.edge_proxy_enabled,
        ",".join(r.prefix for r in EDGE_ROUTES),
    )
