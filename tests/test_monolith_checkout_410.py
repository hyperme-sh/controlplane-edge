"""HTTP 410 for leftover monolith checkout on the gateway edge."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from controlplane_edge.edge_proxy import EdgeProxyMiddleware


@pytest.mark.asyncio
async def test_monolith_checkouts_return_410() -> None:
    app = FastAPI()

    @app.post("/api/v1/checkouts/tenant/subscription")
    async def leftover() -> JSONResponse:
        return JSONResponse({"ok": True})

    app.add_middleware(
        EdgeProxyMiddleware,
        settings=SimpleNamespace(),
        cross=SimpleNamespace(edge_proxy_enabled=True, proxy_timeout_s=5.0),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        gone = await client.post("/api/v1/checkouts/tenant/subscription", json={})
        host = await client.post("/api/v1/checkouts/host/payment/success", json={})
        card = await client.post("/api/v1/payments/stripe/checkout-sessions", json={})
    assert gone.status_code == 410
    assert "/api/v1/payments/usdc/lease-payments" in gone.json()["detail"]
    assert host.status_code == 410
    assert card.status_code == 410
