"""Statement proxy bounds and credential forwarding; HTTP cases run in CI."""
import asyncio
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import Response

from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
from controlplane_edge.edge_proxy import EdgeProxyMiddleware, StorageBodyError, statement_body
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting

PREFIX = '/api/v1/acl/sociacl/statements/forum/'


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,granted,status', [
    ('snapshot', 'acl:statements:read', 403),
    ('append', 'acl:statements:write', 403),
    ('append', 'acl:delegations:read', 403),
    ('snapshot', 'acl:delegations:write', 403),
    ('other', 'acl:delegations:read', 404),
])
async def test_delegation_permissions_do_not_alias_statement_permissions(operation, granted, status):
    proxy = edge(); proxy._dispatch = AsyncMock()
    req = request(path='/api/v1/acl/sociacl/delegations/forum/'+operation, scopes=granted)
    assert (await proxy.dispatch(req, None)).status_code == status
    proxy._dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_delegations_share_statement_tenant_capacity():
    proxy = edge(); proxy._dispatch = AsyncMock(return_value=Response(b'ok'))
    held = [await proxy.dispatch(request(), None) for _ in range(2)]
    delegated = request(path='/api/v1/acl/sociacl/delegations/forum/snapshot', scopes='acl:delegations:read')
    assert (await proxy.dispatch(delegated, None)).status_code == 429
    async def receive(): return {'type':'http.disconnect'}
    async def send(message): pass
    for response in held: await response({'type':'http'}, receive, send)
    assert proxy._statement_capacity.borrowed_tokens == 0


def request(chunks=(), *, tenant='tenant-a', scopes='acl:statements:read', path=PREFIX+'snapshot', method='POST', headers=()):
    parts = iter(chunks)
    async def receive():
        return {'type': 'http.request', 'body': next(parts, b''), 'more_body': False}
    req = Request({'type': 'http', 'method': method, 'path': path,
                   'headers': [(b'content-type', b'application/json'), *headers]}, receive)
    req.state.tenant_id = tenant
    req.state.jwt_claims = {'azp': 'controlplane-api-key', 'scope': scopes}
    return req


def edge():
    return EdgeProxyMiddleware(FastAPI(), settings=OpenAPIAggregationSettings(CPEDGE_ACL_SERVICE_URL='https://acl.owner'))


@pytest.mark.asyncio
@pytest.mark.parametrize('headers,body,status', [
    ([(b'content-length', b'70001')], b'', 413),
    ([], b'x' * 70001, 413),
    ([(b'content-length', b'2')], b'x', 400),
    ([(b'content-length', b'x')], b'', 400),
    ([(b'content-length', b'0'), (b'content-length', b'0')], b'', 400),
    ([(b'content-encoding', b'gzip')], b'', 415),
    ([(b'content-type', b'application/json')], b'', 415),
])
async def test_body_rejections(headers, body, status):
    with pytest.raises(StorageBodyError) as caught:
        await statement_body(request([body], headers=headers))
    assert caught.value.status == status


@pytest.mark.asyncio
async def test_body_boundary_and_timeout(monkeypatch):
    assert len(await statement_body(request([b'x' * 70000]))) == 70000
    timeout = asyncio.timeout
    monkeypatch.setattr('controlplane_edge.edge_proxy.asyncio.timeout', lambda _: timeout(.001))
    async def stalled():
        await asyncio.Event().wait()
    req = request()
    req._receive = stalled
    with pytest.raises(TimeoutError):
        await statement_body(req)


@pytest.mark.asyncio
@pytest.mark.parametrize('kwargs,status', [
    ({'method': 'GET'}, 405), ({'scopes': 'acl:statements:write'}, 403),
    ({'tenant': None}, 403), ({'path': PREFIX+'other'}, 404),
    ({'path': PREFIX+'snapshot/'}, 404),
    ({'path': PREFIX+'append', 'scopes': 'acl:statements:read'}, 403),
])
async def test_invalid_admission_never_reads_or_forwards(kwargs, status):
    proxy = edge()
    proxy._dispatch = AsyncMock()
    assert (await proxy.dispatch(request(**kwargs), None)).status_code == status
    proxy._dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_capacity_is_bounded_partitioned_and_released():
    proxy = edge()
    proxy._dispatch = AsyncMock(return_value=Response(b'ok'))
    held = [await proxy.dispatch(request(), None) for _ in range(2)]
    assert (await proxy.dispatch(request(), None)).status_code == 429
    held += [await proxy.dispatch(request(tenant=f'tenant-{i}'), None) for i in range(6)]
    assert (await proxy.dispatch(request(tenant='new'), None)).status_code == 429
    assert 'new' not in proxy._statement_tenant_capacity
    async def receive(): return {'type': 'http.disconnect'}
    async def send(message): pass
    for response in held:
        await response({'type': 'http'}, receive, send)
    assert proxy._statement_capacity.borrowed_tokens == 0
    assert proxy._statement_tenant_capacity == {}
    proxy._dispatch.side_effect = RuntimeError('upstream failed')
    with pytest.raises(RuntimeError):
        await proxy.dispatch(request(), None)
    assert proxy._statement_capacity.borrowed_tokens == 0
    assert proxy._statement_tenant_capacity == {}


@respx.mock
@pytest.mark.parametrize('operation,scope', [('snapshot', 'read'), ('append', 'write')])
@pytest.mark.parametrize('collection', ['statements', 'delegations'])
def test_exchanged_scope_reaches_owner_and_oversized_body_does_not(monkeypatch, operation, scope, collection):
    prefix = f"/api/v1/acl/sociacl/{collection}/forum/"
    monkeypatch.setenv('CPEDGE_ACL_SERVICE_URL', 'https://acl.owner')
    monkeypatch.setenv('CPEDGE_API_KEYS_SERVICE_URL', 'https://keys.owner')
    tenant = str(uuid.uuid4())
    validate = AsyncMock(return_value={'valid': True, 'key_id': str(uuid.uuid4()),
        'tenant_id': tenant, 'scopes': [f'acl:{collection}:{scope}'], 'purpose': 'service'})
    monkeypatch.setattr('controlplane_edge.middleware.policy.validate_api_key_remote', validate)
    route = respx.post('https://acl.owner' + prefix + operation).mock(return_value=httpx.Response(200, json={'ok': True}))
    app = FastAPI()
    register_gateway_cross_cutting(app)
    headers = {'X-Api-Key': 'private.key', 'X-Tenant-ID': tenant, 'Content-Type': 'application/json'}
    with TestClient(app) as client:
        assert client.post(prefix+operation, content=b'{}', headers=headers).status_code == 200
        assert client.post(prefix+operation, content=b'x'*70001, headers=headers).status_code == 413
        assert client.post(prefix+operation, content=b'{}', headers={**headers, 'Content-Encoding': 'gzip'}).status_code == 415
    assert route.call_count == 1
    sent = route.calls[0].request
    assert sent.content == b'{}'
    assert 'x-api-key' not in sent.headers
    assert sent.headers['x-tenant-id'] == tenant
    from controlplane_identity.security.api_key_exchange_jwt import try_decode_api_key_session_jwt
    claims = try_decode_api_key_session_jwt(sent.headers['authorization'].removeprefix('Bearer '))
    assert claims['scope'] == f'acl:{collection}:{scope}'


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/api/v1/acl/sociacl/unused/../statements/forum/append",
    "/api/v1/acl/sociacl/unused/../delegations/forum/append",
    "/api/v1/acl/sociacl/%64elegations/forum/snapshot",
    "/api/v1/acl/sociacl/./statements/forum/snapshot",
    "/api/v1/acl/sociacl/%73tatements/forum/append",
    "/api/v1/acl/sociacl/unused/%2e%2e/statements/forum/append",
])
async def test_raw_noncanonical_path_never_reads_or_forwards(path):
    proxy = edge()
    proxy._dispatch = AsyncMock()
    req = request([b"x" * 70001], path=path, scopes="unrelated")
    assert (await proxy.dispatch(req, None)).status_code == 400
    proxy._dispatch.assert_not_called()
    assert proxy._statement_capacity.borrowed_tokens == 0
    assert proxy._statement_tenant_capacity == {}


@respx.mock
@pytest.mark.asyncio
async def test_raw_dot_path_cannot_normalize_into_statement_upstream(monkeypatch):
    monkeypatch.setenv('CPEDGE_ACL_SERVICE_URL', 'https://acl.owner')
    monkeypatch.setenv('CPEDGE_API_KEYS_SERVICE_URL', 'https://keys.owner')
    tenant = str(uuid.uuid4())
    monkeypatch.setattr('controlplane_edge.middleware.policy.validate_api_key_remote',
        AsyncMock(return_value={'valid': True, 'key_id': str(uuid.uuid4()),
            'tenant_id': tenant, 'scopes': ['unrelated'], 'purpose': 'service'}))
    upstream = respx.post('https://acl.owner'+PREFIX+'append').mock(return_value=httpx.Response(200))
    app = FastAPI()
    register_gateway_cross_cutting(app)
    raw_path = '/api/v1/acl/sociacl/unused/../statements/forum/append'
    async def raw_app(scope, receive, send):
        await app({**scope, 'path': raw_path, 'raw_path': raw_path.encode()}, receive, send)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=raw_app), base_url='https://gateway.test') as client:
        response = await client.post('/raw', content=b'x'*70001,
            headers={'X-Api-Key': 'private.key', 'X-Tenant-ID': tenant, 'Content-Type': 'application/json'})
    assert response.status_code == 400
    assert not upstream.called
