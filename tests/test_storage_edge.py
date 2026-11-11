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
    return Request({'type':'http','method':method,'path':path,'headers':headers},receive)


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
async def test_storage_requests_limit_concurrent_buffers():
    import asyncio
    from controlplane_edge.edge_proxy import EdgeProxyMiddleware
    from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
    from starlette.responses import Response
    edge=EdgeProxyMiddleware(FastAPI(),settings=OpenAPIAggregationSettings(CPEDGE_STORAGE_SERVICE_URL='https://storage.owner'))
    release=asyncio.Event();eight=asyncio.Event();entered=[]
    async def forward(request,call_next):
        entered.append(request)
        if len(entered)==8: eight.set()
        await release.wait()
        return Response(status_code=204)
    edge._dispatch=forward
    tasks=[asyncio.create_task(edge.dispatch(body_request([]),None)) for _ in range(9)]
    try:
        await asyncio.wait_for(eight.wait(),1)
        assert len(entered)==8
        release.set()
        assert all(row.status_code==204 for row in await asyncio.gather(*tasks))
        assert len(entered)==9
    finally:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
