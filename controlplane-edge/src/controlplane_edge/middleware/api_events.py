"""Optional non-blocking API access envelope after successful responses."""

from __future__ import annotations

import asyncio
import logging
import uuid

from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from controlplane_edge.edge_settings import GatewayCrossCuttingSettings

logger = logging.getLogger(__name__)


class GatewayApiAccessEventMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: GatewayCrossCuttingSettings | None = None) -> None:
        super().__init__(app)
        self._settings = settings or GatewayCrossCuttingSettings()

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if not self._settings.api_access_events_enabled:
            return response
        if response.status_code < 200 or response.status_code >= 300:
            return response
        path = request.url.path
        if not (path.startswith("/api/v1") or path.startswith("/graphql")):
            return response

        tenant_id = getattr(request.state, "tenant_id", None)
        trace_id = request.headers.get("x-request-id") or str(uuid.uuid4())

        asyncio.create_task(
            _publish_access_event(
                request.method,
                path,
                tenant_id,
                trace_id,
            )
        )
        return response


async def _publish_access_event(
    method: str,
    path: str,
    tenant_id: UUID | None,
    trace_id: str,
) -> None:
    try:
        from api.infrastructure.messaging.tenant_event_publisher import get_tenant_event_publisher

        pub = get_tenant_event_publisher()
        await pub.publish(
            tenant_id=tenant_id,
            event_type="gateway_api_access_v1",
            payload={
                "method": method,
                "path": path,
                "trace_id": trace_id,
            },
            correlation_id=trace_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("API access event publish failed (non-fatal): %s", exc)
