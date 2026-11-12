"""Only opaque ciphertext lane operations skip session authentication."""
import uuid
import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from controlplane_edge.rate_limiter import TenantUserRateLimiter
from controlplane_edge.public_paths import is_public_path
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting

PATH = '/api/v1/acl/sociacl/first-contact/' + 'ab' * 32 + '/messages'

@pytest.mark.parametrize('method,path', [('PUT', PATH), ('DELETE', PATH), ('HEAD', PATH),
    ('GET', PATH + '/'), ('GET', PATH + '/admin'), ('POST', PATH.replace('ab' * 32, '~pub')),
    ('GET', PATH.replace('ab' * 32, 'AB' * 32)), ('GET', '/api/v1/acl/sociacl/first-contact'),
    ('GET', '/api/v1/acl/sociacl/keyring/recovery/rows/id')])
def test_lane_exemption_is_exact(method, path):
    assert not is_public_path(path, method)

@respx.mock
def test_ciphertext_proxy_preserves_body_and_anonymous_limits(monkeypatch):
    monkeypatch.setenv('CPEDGE_ACL_SERVICE_URL', 'http://acl.edge.test')
    monkeypatch.setenv('CPEDGE_RATE_LIMIT_PER_MINUTE', '5000')
    app = FastAPI()
    register_gateway_cross_cutting(app)
    app.state.gateway_rate_limiter = TenantUserRateLimiter(per_minute=2)
    ciphertext = b'opaque-encrypted-envelope' * 3
    put = respx.post('http://acl.edge.test' + PATH).mock(return_value=httpx.Response(
        200, json={'id': 'cd' * 32}, headers={'Cache-Control': 'no-store'}))
    get = respx.get('http://acl.edge.test' + PATH).mock(return_value=httpx.Response(
        200, json={'messages': []}, headers={'Cache-Control': 'no-store'}))
    with TestClient(app) as client:
        response = client.post(PATH, content=ciphertext, headers={'Content-Type': 'application/octet-stream', 'X-Tenant-ID': str(uuid.uuid4())})
        assert response.status_code == 200
        assert put.calls.last.request.content == ciphertext
        assert response.headers['cache-control'] == 'no-store'
        assert client.get(PATH, headers={'X-Tenant-ID': str(uuid.uuid4())}).status_code == 200
        assert client.post(PATH, content=ciphertext, headers={'Content-Type': 'application/octet-stream', 'X-Tenant-ID': str(uuid.uuid4())}).status_code == 429
        assert client.delete(PATH).status_code == 401
    assert put.call_count == get.call_count == 1

@respx.mock
def test_lane_proxy_drops_identity_headers_and_bounds_body(monkeypatch):
    monkeypatch.setenv('CPEDGE_ACL_SERVICE_URL', 'http://acl.edge.test')
    monkeypatch.setenv('CPEDGE_RATE_LIMIT_PER_MINUTE', '5000')
    app = FastAPI()
    register_gateway_cross_cutting(app)
    upstream = respx.post('http://acl.edge.test' + PATH).mock(return_value=httpx.Response(200, json={'id': 'cd'*32}))
    with TestClient(app) as client:
        headers = {'Content-Type': 'application/octet-stream', 'Authorization': 'Bearer ignored',
                   'X-Api-Key': 'ignored', 'Cookie': 'session=private', 'X-Tenant-ID': str(uuid.uuid4())}
        assert client.post(PATH, content=b'x'*32, headers=headers).status_code == 200
        sent = upstream.calls.last.request.headers
        for key in ('authorization', 'x-api-key', 'cookie', 'x-tenant-id'):
            assert key not in sent
        assert client.post(PATH, content=b'x'*8193, headers=headers).status_code == 413
    assert upstream.call_count == 1


def test_lane_log_redaction():
    import logging
    from controlplane_edge.lane_access_log import LaneAccessLogFilter
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s %s %s %s %s',
        ('client', 'GET', PATH+'?private=identity', '1.1', 200), None)
    assert LaneAccessLogFilter().filter(record)
    assert 'ab'*32 not in record.getMessage()
    assert 'identity' not in record.getMessage()


def test_lane_concurrency_is_bounded_until_response_cleanup(monkeypatch):
    import asyncio
    from starlette.requests import Request
    from starlette.responses import Response
    from controlplane_edge.edge_proxy import EdgeProxyMiddleware
    monkeypatch.setenv('CPEDGE_ACL_SERVICE_URL', 'http://acl.edge.test')
    async def scenario():
        proxy = EdgeProxyMiddleware(FastAPI())
        calls = []
        async def forward(request, call_next):
            calls.append(request.url.path)
            return Response(b'ciphertext')
        proxy._dispatch = forward
        request = Request({'type': 'http', 'method': 'POST', 'path': PATH, 'headers': [], 'query_string': b''})
        held = [await proxy.dispatch(request, None) for _ in range(8)]
        assert (await proxy.dispatch(request, None)).status_code == 429
        assert len(calls) == 8
        async def receive(): return {'type': 'http.disconnect'}
        async def send(message): pass
        for response in held:
            await response(request.scope, receive, send)
        response = await proxy.dispatch(request, None)
        assert response.status_code == 200
        await response(request.scope, receive, send)
        assert proxy._first_contact_capacity.borrowed_tokens == 0
    asyncio.run(scenario())


def test_lane_never_publishes_tenant_access_event(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from starlette.requests import Request
    from starlette.responses import Response
    from controlplane_edge.middleware.api_events import GatewayApiAccessEventMiddleware
    app = FastAPI(); submitted = []
    app.state.access_event_publisher = SimpleNamespace(submit=lambda *args: submitted.append(args))
    middleware = GatewayApiAccessEventMiddleware(app, settings=SimpleNamespace(api_access_events_enabled=True))
    request = Request({'type': 'http', 'method': 'GET', 'path': PATH, 'headers': [], 'query_string': b'', 'app': app})
    request.state.tenant_id = uuid.uuid4()
    async def response(_): return Response(status_code=200)
    asyncio.run(middleware.dispatch(request, response))
    assert submitted == []
