import json
import logging
import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting
from controlplane_edge.device_transfer import RELAY, ACL, PairingLogFilter

SCOPE = dict(sourceOrigin='https://portal.example', destinationOrigin='https://portal.example', application='hyperme.sh', tenant='00000000-0000-0000-0000-000000000001', audience='test')
PATH = RELAY + '/sessions/' + 'a' * 43 + '/create'
HEADERS = {'Origin': SCOPE['sourceOrigin'], 'X-Pairing-Role': 'receiver', 'X-Pairing-Capability': 'b' * 43}

@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / 'scopes.json'
    path.write_text(json.dumps({'version': 1, 'scopes': [SCOPE]}))
    monkeypatch.setenv('CPEDGE_DEVICE_TRANSFER_SCOPES_FILE', str(path))
    monkeypatch.setenv('CPEDGE_AUTH_SERVICE_URL', 'http://auth.test')
    monkeypatch.setenv('CPEDGE_ACL_SERVICE_URL', 'http://acl.test')
    app = FastAPI(); register_gateway_cross_cutting(app)
    with TestClient(app) as c: yield c

@respx.mock
def test_receiver_bootstrap_is_bounded_and_drops_credentials(client):
    upstream = respx.post('http://auth.test' + PATH).respond(200, json={'v': 1, 'result': {}})
    response = client.post(PATH, json={'scope': SCOPE, 'payload': {}}, headers={**HEADERS, 'Authorization': 'Bearer ignored', 'Cookie': 'private', 'X-Api-Key': 'private', 'X-Tenant-ID': 'untrusted', 'X-Forwarded-For': 'fake'})
    assert response.status_code == 200
    sent = upstream.calls.last.request.headers
    for key in ('authorization', 'cookie', 'x-api-key', 'x-tenant-id', 'x-forwarded-for'): assert key not in sent
    assert sent['x-pairing-capability'] == 'b' * 43
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['access-control-allow-origin'] == SCOPE['sourceOrigin']
    assert client.post(PATH, content=b'x' * 710001, headers={**HEADERS, 'Content-Type': 'application/json'}).status_code == 413
    assert upstream.call_count == 1

@respx.mock
@pytest.mark.parametrize('path,owner', [(ACL+'/state', 'acl'), (RELAY+'/sessions/'+'a'*43+'/admit', 'auth')])
def test_person_owner_gets_only_expected_tenant_bearer(client,path,owner):
    upstream = respx.post('http://'+owner+'.test'+path).respond(403, json={'detail': 'owner refusal'})
    headers={**HEADERS, 'X-Pairing-Role': 'sender', 'Authorization': 'Bearer person.jwt', 'X-Tenant-ID': SCOPE['tenant']}
    assert client.post(path, json={'scope': SCOPE}, headers=headers).status_code == 403
    assert upstream.calls.last.request.headers['authorization'] == 'Bearer person.jwt'
    assert upstream.calls.last.request.headers['x-tenant-id'] == SCOPE['tenant']
    for changed in ({'X-Tenant-ID':'other'}, {'Authorization':'ApiKey secret'}):
        assert client.post(path,json={'scope': SCOPE},headers={**headers,**changed}).status_code == 401
    assert upstream.call_count == 1

@pytest.mark.parametrize('changes', [{'audience':'other'}, {'tenant':'other'}, {'application':'s3r.ch'}, {'destinationOrigin':'https://other.example'}])
def test_scope_refusal(client,changes):
    assert client.post(PATH,json={'scope':{**SCOPE,**changes}},headers=HEADERS).status_code == 403

def test_exact_routes_origin_methods_and_disabled_config(client, monkeypatch):
    for path in (PATH+'/', PATH+'/admin', RELAY+'/credentials', ACL+'/grant'):
        assert client.post(path,json={'scope':SCOPE},headers=HEADERS).status_code == 404
    assert client.post(PATH,json={'scope':SCOPE},headers={**HEADERS,'Origin':'https://evil.example'}).status_code == 403
    assert client.get(PATH,headers=HEADERS).status_code == 405
    assert client.post('/auth/token',json={},headers=HEADERS).status_code == 401
    assert client.options(PATH,headers={'Origin':'https://evil.example','Access-Control-Request-Method':'POST'}).status_code == 403
    monkeypatch.delenv('CPEDGE_DEVICE_TRANSFER_SCOPES_FILE')
    app=FastAPI();register_gateway_cross_cutting(app)
    with TestClient(app) as disabled: assert disabled.post(PATH,json={'scope':SCOPE},headers=HEADERS).status_code == 404

@respx.mock
def test_no_redirect_cookie_or_unbounded_response(client):
    upstream=respx.post('http://auth.test'+PATH).respond(302,headers={'Location':'https://evil.example','Set-Cookie':'private'})
    response=client.post(PATH,json={'scope':SCOPE},headers=HEADERS)
    assert response.status_code == 502 and 'set-cookie' not in response.headers
    upstream.respond(200,content=b'x'*710001,headers={'Content-Type':'application/json'})
    assert client.post(PATH,json={'scope':SCOPE},headers=HEADERS).status_code == 502

def test_rate_limit_ignores_spoofed_address(client):
    for i in range(120):
        assert client.post(PATH,json={},headers={**HEADERS,'X-Forwarded-For':str(i)}).status_code == 403
    assert client.post(PATH,json={},headers=HEADERS).status_code == 429

def test_access_log_removes_path_and_query():
    record=logging.LogRecord('uvicorn.access',20,'',0,'%s %s %s %s %s',('client','POST',PATH+'?secret=private','1.1',200),None)
    assert PairingLogFilter().filter(record)
    from uvicorn.logging import AccessFormatter
    formatted=AccessFormatter('%(request_line)s %(status_code)s',use_colors=False).format(record)
    assert '/device-transfer/[redacted]' in formatted
    assert 'private' not in formatted and 'a'*43 not in formatted
    upstream=logging.LogRecord('httpx',20,'',0,'HTTP Request: %s',('https://edge.example'+PATH,),None)
    assert PairingLogFilter().filter(upstream)
    assert upstream.getMessage() == 'Device transfer request [redacted]'

@respx.mock
def test_s3rch_sender_without_optional_relay_tenant_header(client):
    path=RELAY+'/sessions/'+'a'*43+'/admit'
    upstream=respx.post('http://auth.test'+path).respond(200,json={'v':1,'result':{}})
    headers={**HEADERS,'X-Pairing-Role':'sender','Authorization':'Bearer existing.person'}
    assert client.post(path,json={'scope':SCOPE,'payload':{}},headers=headers).status_code == 200
    assert upstream.calls.last.request.headers['x-tenant-id'] == SCOPE['tenant']
    assert client.post(ACL+'/state',json={'scope':SCOPE},headers=headers).status_code == 401

@respx.mock
def test_proxy_disabled_never_contacts_owner(client, monkeypatch):
    monkeypatch.setenv('CPEDGE_EDGE_PROXY','false')
    app=FastAPI();register_gateway_cross_cutting(app)
    upstream=respx.post('http://auth.test'+PATH).respond(200,json={})
    with TestClient(app) as disabled:
        assert disabled.post(PATH,json={'scope':SCOPE},headers=HEADERS).status_code == 404
        assert disabled.post(ACL+'/state',json={'scope':SCOPE},headers=HEADERS).status_code == 404
    assert upstream.call_count == 0


def test_slow_client_cannot_take_all_slots_and_cancellation_releases(client):
    import asyncio
    from controlplane_edge.device_transfer import DeviceTransferMiddleware

    async def check():
        middleware = DeviceTransferMiddleware(None)
        entered = [asyncio.Event(), asyncio.Event()]
        never = asyncio.Event()

        async def call(address, receive):
            messages = []
            async def send(message):
                messages.append(message)
            scope = {'type': 'http', 'method': 'POST', 'path': PATH,
                     'raw_path': PATH.encode(), 'query_string': b'',
                     'scheme': 'https', 'server': ('edge.example', 443),
                     'client': (address, 1234),
                     'headers': [(b'origin', SCOPE['sourceOrigin'].encode()),
                                 (b'content-type', b'application/json'),
                                 (b'x-forwarded-for', b'forged')]}
            await middleware(scope, receive, send)
            return messages[0]['status']

        async def slow(index):
            entered[index].set()
            await never.wait()

        async def complete():
            return {'type': 'http.request', 'body': b'{}', 'more_body': False}

        tasks = [asyncio.create_task(call('attacker', lambda i=i: slow(i))) for i in range(2)]
        try:
            await asyncio.wait_for(asyncio.gather(*(e.wait() for e in entered)), 1)
            assert await call('attacker', complete) == 429
            assert await call('other-client', complete) == 403
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert not middleware.active_clients
        assert middleware.capacity.borrowed_tokens == 0
        assert await call('attacker', complete) == 403
    asyncio.run(check())


def test_slow_body_deadline_releases_capacity(client, monkeypatch):
    import asyncio
    import controlplane_edge.device_transfer as transfer
    monkeypatch.setattr(transfer, 'BODY_TIMEOUT', 0.01)

    async def check():
        middleware = transfer.DeviceTransferMiddleware(None)
        async def receive():
            await asyncio.Event().wait()
        messages = []
        async def send(message):
            messages.append(message)
        scope = {'type': 'http', 'method': 'POST', 'path': PATH,
                 'raw_path': PATH.encode(), 'query_string': b'',
                 'scheme': 'https', 'server': ('edge.example', 443),
                 'client': ('slow-client', 1234),
                 'headers': [(b'origin', SCOPE['sourceOrigin'].encode()),
                             (b'content-type', b'application/json')]}
        await asyncio.wait_for(middleware(scope, receive, send), 1)
        assert messages[0]['status'] == 503
        assert not middleware.active_clients
        assert middleware.capacity.borrowed_tokens == 0
    asyncio.run(check())


@pytest.mark.parametrize('cancel', [False, True])
def test_slow_reader_holds_slots_until_timeout_or_cancellation(client, monkeypatch, cancel):
    import asyncio
    import controlplane_edge.device_transfer as transfer
    monkeypatch.setattr(transfer, 'SEND_TIMEOUT', 1 if cancel else 0.02)

    async def check():
        middleware = transfer.DeviceTransferMiddleware(None)
        entered = asyncio.Event()
        async def forward(request):
            return 200, b'owner response', {}
        middleware.forward = forward
        async def receive():
            raise AssertionError('No body needed by stub owner')
        async def send(message):
            if message['type'] == 'http.response.body':
                entered.set()
                await asyncio.Event().wait()
        scope = {'type': 'http', 'method': 'POST', 'path': PATH,
                 'headers': [], 'client': ('slow-reader', 1234)}
        task = asyncio.create_task(middleware(scope, receive, send))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert middleware.active_clients == {'slow-reader': 1}
            assert middleware.capacity.borrowed_tokens == 1
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await asyncio.wait_for(task, 1)
            assert not middleware.active_clients
            assert middleware.capacity.borrowed_tokens == 0
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(check())
