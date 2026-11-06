import asyncio
import json
import uuid

import httpx
import pytest
import respx
from controlplane_edge.edge_settings import GatewayCrossCuttingSettings
from controlplane_edge.middleware.api_events import AccessEventPublisher


def settings(**kw):
    return GatewayCrossCuttingSettings(CPEDGE_API_ACCESS_EVENTS=True,
        CPEDGE_EVENTS_URL='http://events.fixture', CPEDGE_EVENTS_TOKEN='producer-secret', **kw)


@pytest.mark.asyncio
async def test_delivery_has_owner_identity_and_idempotency():
    with respx.mock() as mock:
        route = mock.post('http://events.fixture/events').mock(return_value=httpx.Response(200, json={'committed':True}))
        tenant = uuid.uuid4()
        async with AccessEventPublisher(settings()) as publisher:
            publisher.submit('GET', '/api/v1/users', tenant)
            publisher.submit('GET', '/api/v1/health', None)
        assert route.call_count == 1
        request = route.calls[0].request
        body = json.loads(request.content)
        assert request.headers['Authorization'] == 'Bearer producer-secret'
        assert request.headers['Idempotency-Key'] == body['event_id']
        assert body['envelope']['service'] == 'controlplane-edge'
        assert body['envelope']['tenant_id'] == str(tenant)
        assert body['envelope']['payload'] == {'method':'GET', 'path':'/api/v1/users', 'trace_id':body['event_id']}


@pytest.mark.asyncio
async def test_enable_without_owner_configuration_fails_startup():
    with pytest.raises(ValueError, match='CPEDGE_EVENTS_URL'):
        async with AccessEventPublisher(GatewayCrossCuttingSettings(CPEDGE_API_ACCESS_EVENTS=True)):
            pass


@pytest.mark.asyncio
async def test_delivery_failures_do_not_stop_worker_and_queue_is_bounded(caplog):
    with respx.mock() as mock:
        route = mock.post('http://events.fixture/events').mock(side_effect=[httpx.Response(503), httpx.Response(200)])
        async with AccessEventPublisher(settings()) as publisher:
            publisher.submit('GET', '/api/v1/users', uuid.uuid4())
            publisher.submit('GET', '/api/v1/users', uuid.uuid4())
        assert route.call_count == 2
        assert 'delivery failed' in caplog.text
        assert 'producer-secret' not in caplog.text
    publisher = AccessEventPublisher(settings())
    publisher.worker = object()
    for _ in range(129):
        publisher.submit('GET', '/api/v1/users', uuid.uuid4())
    assert publisher.queue.qsize() == 128
    assert 'queue full' in caplog.text
