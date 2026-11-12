"""Mount-less HTTP reverse proxy from the gateway to extracted services."""

from __future__ import annotations

import asyncio
import anyio
import re
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

from controlplane_edge.public_paths import is_sumsub_webhook_path, is_contact_lane_path

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
    bearer = getattr(request.state, "bearer_token", None)
    for key, value in request.headers.items():
        lk = key.lower()
        if (lk in _HOP_BY_HOP or lk in {"authorization", "x-tenant-id"}
                or (lk == "x-api-key" and bearer)):
            continue
        out[key] = value

    tenant = getattr(request.state, "tenant_id", None)
    if tenant is not None:
        out["X-Tenant-ID"] = str(tenant)

    # The exchange token replaces the raw API key as the upstream authority.
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


class StorageBodyError(ValueError):
    def __init__(self, status):
        self.status = status


async def storage_body(request: Request) -> bytes:
    maximum = 64 * 1024 * 1024 if request.method == 'PUT' and request.url.path.startswith('/api/v1/storage/objects/') else 8192
    values = request.headers.getlist('content-length')
    if len(values) != 1 or not re.fullmatch('[0-9]{1,9}', values[0]):
        # Empty GET/HEAD/DELETE requests need no declared body.
        if request.method in ('GET','HEAD','DELETE') and not values:
            expected = 0
        else:
            raise StorageBodyError(411)
    else:
        expected = int(values[0])
    if expected > maximum:
        raise StorageBodyError(413)
    if request.headers.getlist('content-encoding') not in ([], ['identity']):
        raise StorageBodyError(415)
    body = bytearray()
    async with asyncio.timeout(30):
        async for chunk in request.stream():
            if len(body) + len(chunk) > expected:
                raise StorageBodyError(413)
            body.extend(chunk)
    if len(body) != expected:
        raise StorageBodyError(400)
    return bytes(body)


class StorageCapacityResponse(Response):
    """Keep upload memory accounted for until response cleanup completes."""
    def __init__(self, response: Response, capacity, borrower, release_tenant=None):
        super().__init__(status_code=response.status_code)
        self.raw_headers = response.raw_headers
        self._response = response
        self._capacity, self._borrower = capacity, borrower
        self._release_tenant = release_tenant

    async def __call__(self, scope, receive, send):
        try:
            await self._response(scope, receive, send)
        finally:
            # The upstream response can retain its request's upload bytes.
            self._response = None
            self._capacity.release_on_behalf_of(self._borrower)
            if self._release_tenant is not None:
                self._release_tenant()


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
        self._storage_capacity = anyio.CapacityLimiter(8)
        self._lane_capacity = anyio.CapacityLimiter(16)
        self._storage_tenant_capacity = {}

    async def dispatch(self, request: Request, call_next) -> Response:
        match = match_edge_route(request.url.path, self._settings)
        if match and is_contact_lane_path(request.url.path, request.method):
            borrower = object()
            try:
                self._lane_capacity.acquire_on_behalf_of_nowait(borrower)
            except anyio.WouldBlock:
                return Response(status_code=429, headers={"Retry-After": "1"})
            try:
                response = await self._dispatch(request, call_next)
                return StorageCapacityResponse(response, self._lane_capacity, borrower)
            except BaseException:
                self._lane_capacity.release_on_behalf_of(borrower)
                raise
        if (match and match.service_id == 'storage' and request.method == 'PUT'
                and request.url.path.startswith('/api/v1/storage/objects/')):
            # Only object uploads can buffer 64 MiB. Administrative bodies are
            # limited to 8 KiB and must not reserve object-upload capacity.
            claims = getattr(request.state, "jwt_claims", None) or {}
            scopes = claims.get("scope")
            if (claims.get("azp") != "controlplane-api-key"
                    or not isinstance(scopes, str)
                    or "storage:objects:write" not in scopes.split()):
                return Response(status_code=403)
            borrower = object()
            tenant = str(getattr(request.state, "tenant_id", None))
            capacity = self._storage_tenant_capacity.setdefault(tenant, anyio.CapacityLimiter(2))
            try:
                capacity.acquire_on_behalf_of_nowait(borrower)
            except anyio.WouldBlock:
                return Response(status_code=429, headers={"Retry-After": "1"})

            def release_tenant():
                capacity.release_on_behalf_of(borrower)
                if not capacity.borrowed_tokens:
                    self._storage_tenant_capacity.pop(tenant, None)

            acquired = False
            try:
                with anyio.fail_after(120):
                    await self._storage_capacity.acquire_on_behalf_of(borrower)
                    acquired = True
                    response = await self._dispatch(request, call_next)
                return StorageCapacityResponse(response, self._storage_capacity, borrower, release_tenant)
            except BaseException as error:
                if acquired:
                    self._storage_capacity.release_on_behalf_of(borrower)
                release_tenant()
                if isinstance(error, TimeoutError):
                    return Response(status_code=408)
                raise
        return await self._dispatch(request, call_next)

    async def _dispatch(self, request: Request, call_next) -> Response:
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

        if is_sumsub_webhook_path(request.url.path, request.method):
            headers = {}
            for name in ("x-payload-digest-alg", "x-payload-digest"):
                values = request.headers.getlist(name)
                if len(values) != 1:
                    return Response(status_code=401)
                headers[name] = values[0]
            if request.headers.getlist("content-encoding") not in ([], ["identity"]):
                return Response(status_code=415)
            payload = bytearray()
            try:
                async with asyncio.timeout(5):
                    async for chunk in request.stream():
                        if len(payload) + len(chunk) > 65536:
                            return Response(status_code=413)
                        payload.extend(chunk)
            except TimeoutError:
                return Response(status_code=408)
            body = bytes(payload)
        elif is_contact_lane_path(request.url.path, request.method):
            # Do not forward identity headers/cookies or buffer an unbounded body
            # before the ACL service can apply its ciphertext size limit.
            headers = {"Content-Type": request.headers.get("content-type", "")}
            if request.headers.getlist("content-encoding") not in ([], ["identity"]):
                return Response(status_code=415)
            payload = bytearray()
            try:
                async with asyncio.timeout(30):
                    async for chunk in request.stream():
                        if len(payload) + len(chunk) > 65536:
                            return Response(status_code=413)
                        payload.extend(chunk)
            except TimeoutError:
                return Response(status_code=408)
            body = bytes(payload)
        elif match.service_id == 'storage':
            try:
                body = await storage_body(request)
            except StorageBodyError as exc:
                return Response(status_code=exc.status)
            except TimeoutError:
                return Response(status_code=408)
            headers = _forward_request_headers(request)
        else:
            body = await request.body()
            headers = _forward_request_headers(request)
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
            headers=headers,
            content=body,
            extensions={"timeout": timeout.as_dict()},
        )
        try:
            upstream = await client.send(upstream_request, stream=True, follow_redirects=False)
        except httpx.HTTPError as exc:
            logger.warning(
                "edge proxy upstream error service=%s: %s",
                match.service_id,
                type(exc).__name__,
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

        async def _release() -> None:
            await upstream.aclose()
            if own_client:
                await client.aclose()

        response = StreamingResponse(
            # Decoded, because content-encoding is stripped from the response.
            upstream.aiter_bytes(),
            status_code=upstream.status_code,
            background=BackgroundTask(_release),
        )
        # Keep repeated fields separate, especially Set-Cookie's Expires commas.
        # ASGI response header names are lowercase; values remain original bytes.
        response.raw_headers = [
            (name.lower(), value) for name, value in upstream.headers.raw
            if name.decode("latin-1").lower() not in _STRIP_RESPONSE
        ]
        return response


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
