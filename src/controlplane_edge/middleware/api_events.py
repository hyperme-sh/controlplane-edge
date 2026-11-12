"""Bounded best-effort access telemetry sent to the events owner's HTTP inbox."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import uuid

import httpx
from datetime import datetime, timezone
from starlette.middleware.base import BaseHTTPMiddleware
from controlplane_edge.edge_settings import GatewayCrossCuttingSettings

logger = logging.getLogger(__name__)


class AccessEventPublisher:
    def __init__(self, settings: GatewayCrossCuttingSettings):
        self.settings = settings
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=128)
        self.client = None
        self.worker = None

    async def __aenter__(self):
        if self.settings.api_access_events_enabled:
            url = self.settings.events_url
            if not url or httpx.URL(url).scheme not in {'http', 'https'} or not self.settings.events_token.get_secret_value():
                raise ValueError('Access events require CPEDGE_EVENTS_URL and CPEDGE_EVENTS_TOKEN')
            self.client = httpx.AsyncClient(timeout=5.0, follow_redirects=False)
            self.worker = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, *args):
        if self.worker:
            try:
                await asyncio.wait_for(self.queue.join(), timeout=5.0)
            except TimeoutError:
                logger.warning('Access events shutdown timed out; pending telemetry dropped')
            finally:
                self.worker.cancel()
                with suppress(asyncio.CancelledError):
                    await self.worker
                await self.client.aclose()

    def submit(self, method: str, path: str, tenant_id: uuid.UUID):
        if not self.worker or tenant_id is None:
            return
        event_id = str(uuid.uuid4())
        envelope = {
            'schema_version': 1, 'event_type': 'gateway_api_access_v1',
            'service': 'controlplane-edge', 'tenant_id': str(tenant_id),
            'occurred_at': datetime.now(timezone.utc).isoformat(), 'correlation_id': event_id,
            'payload': {'method': method[:32], 'path': path[:4096], 'trace_id': event_id},
        }
        try:
            self.queue.put_nowait({'event_id': event_id, 'envelope': envelope})
        except asyncio.QueueFull:
            logger.warning('Access events queue full; telemetry dropped')

    async def _run(self):
        while True:
            delivery = await self.queue.get()
            try:
                response = await self.client.post(
                    self.settings.events_url.rstrip('/') + '/events', json=delivery,
                    headers={'Authorization': 'Bearer ' + self.settings.events_token.get_secret_value(),
                             'Idempotency-Key': delivery['event_id']})
                response.raise_for_status()
            except Exception as exc:
                # Never log the request URL, credentials or response body.
                logger.warning('Access event delivery failed (%s)', type(exc).__name__)
            finally:
                self.queue.task_done()


class GatewayApiAccessEventMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: GatewayCrossCuttingSettings | None = None):
        super().__init__(app)
        self._settings = settings or GatewayCrossCuttingSettings()

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if self._settings.api_access_events_enabled and 200 <= response.status_code < 300:
            path = request.url.path
            if path.startswith('/api/v1/acl/sociacl/contact-lanes/'):
                return response  # Never correlate an opaque lane with a tenant.
            if path == '/api/v1' or path.startswith('/api/v1/') or path == '/graphql':
                publisher = getattr(request.app.state, 'access_event_publisher', None)
                tenant = getattr(request.state, 'tenant_id', None)
                if publisher and tenant:
                    publisher.submit(request.method, path, tenant)
        return response
