"""Actual edge proxy and token verifier; only registry and upstream HTTP are substituted."""
import json
import uuid
import httpx
import pytest
import respx
from controlplane_identity import nightly
from controlplane_identity.configuration import settings
from controlplane_identity.nightly_http import Authority
from controlplane_identity.security.tenant_session_jwt import mint_tenant_session_jwt
from controlplane_edge.nightly import EdgeRunMiddleware
from controlplane_edge.auth_utils import resolve_bearer_claims, resolve_bearer_claims_sync
from test_edge_proxy import edge_app, _fake_bearer

SUB='11111111-1111-4111-8111-111111111111';TENANT='22222222-2222-4222-8222-222222222222'
SCOPE=dict(suite='portal-device-transfer',subject=SUB,tenant=TENANT,organization='',realm='controlplane',issuer='https://auth.test.hyperme.sh/realms/controlplane',clients=['controlplane-frontend'],origins=['https://portal.test.hyperme.sh'],identities={'sea':[]})
BINDING=dict(version=1,owner='edge',run='123-1-portal-device-transfer',generation='c'*64,scope=SCOPE,operation='33333333-3333-4333-8333-333333333333')
CONFIG=dict(version=1,owner='edge',origin='https://api.test.hyperme.sh',authOrigin='https://api.test.hyperme.sh',ownerKey='a'*64,controllerKey='b'*64,scopes={SCOPE['suite']:SCOPE})


@pytest.mark.asyncio
async def test_native_proxy_forwards_only_admitted_grant(edge_app,monkeypatch):
    monkeypatch.setattr(nightly,'_subjects',frozenset())
    monkeypatch.setattr(settings,'api_key_exchange_jwt_secret','native-edge-unit-secret-32-characters-minimum')
    with nightly.admitted_run(BINDING):
        token=mint_tenant_session_jwt(claims={'sub':SUB,'nightly_run':{k:BINDING[k] for k in ('run','generation')}},tenant_id=uuid.UUID(TENANT))
    calls=[];active=[True]
    def registry(request):
        value=json.loads(request.content);calls.append(value['action'])
        if value['action']=='admit':return httpx.Response(200,json=BINDING) if active[0] else httpx.Response(409)
        assert value['action']=='complete'
        return httpx.Response(200,json={k:BINDING[k] for k in ('version','owner','run','generation','operation')}|{'completed':True})
    edge_app.add_middleware(EdgeRunMiddleware,authority=Authority(CONFIG,'edge',httpx.MockTransport(registry)))
    def upstream(request):
        assert calls==['admit']
        assert request.headers['X-Nightly-Run-Grant']=='d'*64
        assert request.headers['Authorization']=='Bearer '+token
        assert request.headers['X-Tenant-ID']==TENANT
        return httpx.Response(200,json={'sub':SUB})
    with respx.mock(assert_all_called=False) as mock:
        owner=mock.get('http://auth.edge.test/auth/me').mock(side_effect=upstream)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=edge_app),base_url=CONFIG['origin']) as client:
            headers={'Authorization':'Bearer '+token,'X-Nightly-Run-Grant':'d'*64}
            assert (await client.get('/auth/me',headers=headers)).status_code==200
            assert calls==['admit','complete']
            assert (await client.post('/auth/enrollment/grant',headers=headers)).status_code==409
            active[0]=False
            assert (await client.get('/auth/me',headers=headers)).status_code==409
            assert owner.call_count==1


@pytest.mark.asyncio
async def test_dev_decode_cannot_accept_managed_fixture(edge_app,monkeypatch):
    monkeypatch.setattr(nightly,'_subjects',frozenset({SUB}))
    token=_fake_bearer(sub=SUB,tenant=TENANT)
    assert await resolve_bearer_claims(token) is None
    assert resolve_bearer_claims_sync(token) is None


@pytest.mark.asyncio
async def test_admitted_telemetry_waits_for_native_acknowledgement():
    import asyncio
    from controlplane_edge.middleware.api_events import AccessEventPublisher
    from controlplane_edge.edge_settings import GatewayCrossCuttingSettings
    settings=GatewayCrossCuttingSettings(CPEDGE_EVENTS_URL='https://events.unit',CPEDGE_EVENTS_TOKEN='isolated-token')
    publisher=AccessEventPublisher(settings)
    entered=asyncio.Event();finish=asyncio.Event()
    async def transport(request):
        entered.set();await finish.wait()
        assert request.headers['Idempotency-Key']==json.loads(request.content)['event_id']
        return httpx.Response(202)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        publisher.client=client
        task=asyncio.create_task(publisher.submit_admitted('GET','/api/v1/organizations',uuid.UUID(TENANT)))
        await asyncio.wait_for(entered.wait(),timeout=2)
        assert not task.done() and publisher.queue.empty()
        finish.set();await task
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(503))) as client:
        publisher.client=client
        with pytest.raises(httpx.HTTPStatusError):await publisher.submit_admitted('GET','/api/v1/organizations',uuid.UUID(TENANT))


@pytest.mark.asyncio
async def test_native_org_proxy_retains_only_root_declared_tenant_for_provider_token(edge_app,monkeypatch):
    from controlplane_identity.nightly import require_original_run
    # Substitute only verified provider output; native edge policy/proxy remains real.
    async def verified(token):
        claims={'sub':SUB,'nightly_run':{k:BINDING[k] for k in ('run','generation')}}
        require_original_run(claims);return claims
    monkeypatch.setattr('controlplane_edge.middleware.policy.resolve_bearer_claims',verified)
    calls=[]
    def registry(request):
        value=json.loads(request.content);calls.append(value['action'])
        if value['action']=='admit':return httpx.Response(200,json=BINDING)
        return httpx.Response(200,json={k:BINDING[k] for k in ('version','owner','run','generation','operation')}|{'completed':True})
    edge_app.add_middleware(EdgeRunMiddleware,authority=Authority(CONFIG,'edge',httpx.MockTransport(registry)))
    def upstream(request):
        assert request.headers['X-Tenant-ID']==TENANT
        assert request.headers['X-Nightly-Run-Grant']=='d'*64
        return httpx.Response(200,json={'items':[],'total':0})
    with respx.mock(assert_all_called=False) as mock:
        target=mock.get('http://user.edge.test/api/v1/organizations').mock(side_effect=upstream)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(edge_app),base_url=CONFIG['origin']) as client:
            headers={'Authorization':'Bearer provider-substitution','X-Nightly-Run-Grant':'d'*64,'X-Tenant-ID':TENANT}
            response=await client.get('/api/v1/organizations',headers=headers)
            assert response.status_code==200,response.text
            assert calls==['admit','complete']
            assert (await client.get('/api/v1/organizations',headers=headers|{'X-Tenant-ID':str(uuid.uuid4())})).status_code==409
            assert target.call_count==1 and calls==['admit','complete','admit']
