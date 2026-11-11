"""Bounded storage proxy units using in-memory upstreams only."""
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from controlplane_identity.security.api_key_exchange_jwt import try_decode_api_key_session_jwt
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting
from controlplane_edge.edge_proxy import StorageBodyError, storage_body


def body_request(chunks, headers=(), method='PUT', path='/api/v1/storage/objects/'+'a'*64):
    parts=iter(chunks)
    async def receive():
        try: return {'type':'http.request','body':next(parts),'more_body':True}
        except StopIteration: return {'type':'http.request','body':b'','more_body':False}
    request = Request({'type':'http','method':method,'path':path,'headers':headers},receive)
    request.state.jwt_claims = {'azp': 'controlplane-api-key', 'scope': 'storage:objects:write'}
    return request


@pytest.mark.parametrize('length,chunks,status',[(None,[b'x'],411),('67108865',[],413),('1',[b'xx'],413),('2',[b'x'],400),('bad',[],411)])
@pytest.mark.asyncio
async def test_storage_body_rejects_invalid_size(length,chunks,status):
    headers=[] if length is None else [(b'content-length',length.encode())]
    with pytest.raises(StorageBodyError) as caught: await storage_body(body_request(chunks,headers))
    assert caught.value.status==status


@pytest.mark.asyncio
async def test_storage_body_preserves_binary_and_bounds_admin_requests():
    assert await storage_body(body_request([b'\x00',b'\xff'],[(b'content-length',b'2')]))==b'\x00\xff'
    assert await storage_body(body_request([],method='HEAD'))==b''
    for headers,status in [([(b'content-length',b'0'),(b'content-length',b'0')],411), ([(b'content-length',b'0'),(b'content-encoding',b'gzip')],415), ([(b'content-length',b'8193')],413)]:
        with pytest.raises(StorageBodyError) as caught:
            await storage_body(body_request([],headers,method='POST',path='/api/v1/storage/tenant/configure'))
        assert caught.value.status==status


@respx.mock
def test_storage_proxy_exchanges_key_and_preserves_opaque_body(monkeypatch):
    monkeypatch.setenv('CPEDGE_STORAGE_SERVICE_URL','https://storage.owner')
    monkeypatch.setenv('CPEDGE_API_KEYS_SERVICE_URL','https://keys.owner')
    tenant,key_id=uuid.uuid4(),uuid.uuid4()
    validate=AsyncMock(return_value={'valid':True,'key_id':str(key_id),'tenant_id':str(tenant),'scopes':['storage:objects:write'],'purpose':'service'})
    monkeypatch.setattr('controlplane_edge.middleware.policy.validate_api_key_remote',validate)
    route=respx.put('https://storage.owner/api/v1/storage/objects/'+'a'*64).mock(return_value=httpx.Response(201))
    app=FastAPI();register_gateway_cross_cutting(app)
    with TestClient(app) as client:
        response=client.put('/api/v1/storage/objects/'+'a'*64,content=b'\x00\xff',headers={'X-Api-Key':'private.key','X-Tenant-ID':str(tenant),'Content-Type':'application/octet-stream'})
        assert response.status_code==201
        assert client.put('/api/v1/storage/objects/'+'a'*64,content=b'x').status_code==401
        auth={'X-Api-Key':'private.key','X-Tenant-ID':str(tenant)}
        for extra,status in [({'Content-Length':'3'},400),({'Content-Encoding':'gzip'},415),({'Content-Length':'67108865'},413)]:
            rejected=client.put('/api/v1/storage/objects/'+'a'*64,content=b'x',headers={**auth,**extra})
            assert rejected.status_code==status
        assert route.call_count==1
    request=route.calls[0].request
    assert request.content==b'\x00\xff'
    assert request.headers['content-length']=='2'
    assert 'x-api-key' not in request.headers
    claims=try_decode_api_key_session_jwt(request.headers['authorization'].removeprefix('Bearer '))
    assert claims['https://spanopticon.dev/tenant_id']==str(tenant)
    assert claims['scope']=='storage:objects:write'
    assert claims['exp']-claims['iat']<=300


@pytest.mark.asyncio
async def test_stalled_storage_body_times_out(monkeypatch):
    import asyncio
    from controlplane_edge import edge_proxy
    timeout=asyncio.timeout
    monkeypatch.setattr(edge_proxy.asyncio,'timeout',lambda _:timeout(0.001))
    async def receive():
        await asyncio.sleep(1)
        return {'type':'http.request','body':b'', 'more_body':False}
    req=Request({'type':'http','method':'PUT','path':'/api/v1/storage/objects/x','headers':[(b'content-length',b'1')]},receive)
    with pytest.raises(TimeoutError): await storage_body(req)


@pytest.mark.asyncio
async def test_storage_requests_hold_capacity_until_response_consumption():
    import asyncio
    from controlplane_edge.edge_proxy import EdgeProxyMiddleware
    from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
    from starlette.responses import Response
    edge=EdgeProxyMiddleware(FastAPI(),settings=OpenAPIAggregationSettings(CPEDGE_STORAGE_SERVICE_URL='https://storage.owner'))
    async def forward(request,call_next): return Response(content=b'upstream response')
    edge._dispatch=forward
    def tenant_request():
        request = body_request([])
        request.state.tenant_id = uuid.uuid4()
        return request
    responses=[await edge.dispatch(tenant_request(),None) for _ in range(8)]
    assert edge._storage_capacity.borrowed_tokens==8
    waiting=asyncio.create_task(edge.dispatch(tenant_request(),None))
    async def receive(): return {'type':'http.disconnect'}
    async def send(message): pass
    try:
        await asyncio.sleep(0)
        assert not waiting.done()
        for response in responses:
            await response({'type':'http'},receive,send)
            assert response._response is None
        last=await asyncio.wait_for(waiting,1)
        assert edge._storage_capacity.borrowed_tokens==1
        await last({'type':'http'},receive,send)
        assert edge._storage_capacity.borrowed_tokens==0
    finally:
        waiting.cancel()
        await asyncio.gather(waiting,return_exceptions=True)


@pytest.mark.asyncio
async def test_storage_response_releases_capacity_on_disconnect():
    import anyio
    from controlplane_edge.edge_proxy import StorageCapacityResponse
    from starlette.responses import Response
    capacity=anyio.CapacityLimiter(1);borrower=object()
    await capacity.acquire_on_behalf_of(borrower)
    response=StorageCapacityResponse(Response(b'held upload'),capacity,borrower)
    async def receive(): return {'type':'http.disconnect'}
    async def send(message): raise ConnectionError('client disconnected')
    with pytest.raises(ConnectionError): await response({'type':'http'},receive,send)
    assert response._response is None
    assert capacity.borrowed_tokens==0


@pytest.mark.asyncio
async def test_slow_storage_downloads_do_not_reserve_upload_capacity():
    from controlplane_edge.edge_proxy import EdgeProxyMiddleware
    from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
    from starlette.responses import StreamingResponse
    import asyncio

    edge = EdgeProxyMiddleware(FastAPI(), settings=OpenAPIAggregationSettings(
        CPEDGE_STORAGE_SERVICE_URL='https://storage.owner'))
    async def slow_body():
        await asyncio.Event().wait()
        yield b'chunk'
    async def forward(request, call_next):
        return StreamingResponse(slow_body())
    edge._dispatch = forward
    responses = [await asyncio.wait_for(edge.dispatch(
        body_request([], method='GET'), None), 1) for _ in range(9)]
    assert edge._storage_capacity.borrowed_tokens == 0
    # Unconsumed downloads cannot prevent an upload from being admitted.
    upload = await asyncio.wait_for(edge.dispatch(body_request([]), None), 1)
    assert edge._storage_capacity.borrowed_tokens == 1
    async def receive(): return {'type': 'http.disconnect'}
    async def send(message): pass
    await upload({'type': 'http'}, receive, send)
    assert edge._storage_capacity.borrowed_tokens == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['GET', 'HEAD', 'DELETE', 'PUT'])
async def test_storage_body_timeout_returns_408_for_every_method(monkeypatch, method):
    from controlplane_edge import edge_proxy
    from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
    edge = edge_proxy.EdgeProxyMiddleware(FastAPI(), settings=OpenAPIAggregationSettings(
        CPEDGE_STORAGE_SERVICE_URL='https://storage.owner'))
    monkeypatch.setattr(edge_proxy, 'storage_body', AsyncMock(side_effect=TimeoutError))
    response = await edge.dispatch(body_request([], method=method), None)
    assert response.status_code == 408
    async def receive(): return {'type': 'http.disconnect'}
    async def send(message): pass
    await response({'type': 'http'}, receive, send)
    assert edge._storage_capacity.borrowed_tokens == 0


@pytest.mark.asyncio
async def test_storage_upload_admission_is_partitioned_by_tenant():
    from controlplane_edge.edge_proxy import EdgeProxyMiddleware
    from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
    from starlette.responses import Response
    edge = EdgeProxyMiddleware(FastAPI(), settings=OpenAPIAggregationSettings(
        CPEDGE_STORAGE_SERVICE_URL='https://storage.owner'))
    async def forward(request, call_next): return Response(b'buffer retained')
    edge._dispatch = forward
    def request(tenant):
        req = body_request([])
        req.state.tenant_id = tenant
        return req
    held = [await edge.dispatch(request('tenant-a'), None) for _ in range(2)]
    refused = await edge.dispatch(request('tenant-a'), None)
    assert refused.status_code == 429
    held.append(await edge.dispatch(request('tenant-b'), None))
    assert held[-1].status_code == 200
    assert edge._storage_capacity.borrowed_tokens == 3
    async def receive(): return {'type': 'http.disconnect'}
    async def send(message): pass
    for response in held:
        await response({'type': 'http'}, receive, send)
    assert edge._storage_capacity.borrowed_tokens == 0
    assert edge._storage_tenant_capacity == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('claims', [{}, {'azp': 'tenant-session', 'scope': 'storage:objects:write'},
                                   {'azp': 'controlplane-api-key', 'scope': 'storage:objects:read'}])
async def test_unscoped_member_cannot_reserve_upload_slots(monkeypatch, claims):
    from controlplane_edge.edge_proxy import EdgeProxyMiddleware
    from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
    edge = EdgeProxyMiddleware(FastAPI(), settings=OpenAPIAggregationSettings(
        CPEDGE_STORAGE_SERVICE_URL='https://storage.owner'))
    forward = AsyncMock()
    edge._dispatch = forward
    request = body_request([])
    request.state.jwt_claims = claims
    response = await edge.dispatch(request, None)
    assert response.status_code == 403
    forward.assert_not_called()
    assert edge._storage_capacity.borrowed_tokens == 0
    assert edge._storage_tenant_capacity == {}


@pytest.mark.asyncio
async def test_small_admin_bodies_cannot_reserve_object_upload_slots():
    from controlplane_edge.edge_proxy import EdgeProxyMiddleware
    from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
    from starlette.responses import Response
    edge = EdgeProxyMiddleware(FastAPI(), settings=OpenAPIAggregationSettings(
        CPEDGE_STORAGE_SERVICE_URL='https://storage.owner'))
    async def forward(request, call_next): return Response(b'admin response')
    edge._dispatch = forward
    for _ in range(9):
        request = body_request([], method='POST', path='/api/v1/storage/tenant/configure')
        request.state.jwt_claims = {}
        assert (await edge.dispatch(request, None)).status_code == 200
    assert edge._storage_capacity.borrowed_tokens == 0
    assert edge._storage_tenant_capacity == {}
