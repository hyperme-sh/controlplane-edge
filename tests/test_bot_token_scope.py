"""Scoped forwarding unit contracts; the owner remains the authenticator."""
import uuid
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from controlplane_edge.middleware.policy import GatewayAuthMiddleware, bot_agent_route
from controlplane_edge.edge_settings import GatewayCrossCuttingSettings

BOT = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
TENANT = '11111111-2222-4333-8444-555555555555'
TOKEN = 'hm_bot_' + 'a' * 64


def app(monkeypatch, enabled=True):
    async def reject(*args): return None
    monkeypatch.setattr('controlplane_edge.middleware.policy.resolve_bearer_claims', reject)
    monkeypatch.setattr('controlplane_edge.middleware.policy.resolve_setup_claims', reject)
    instance = FastAPI()
    instance.state.forwarded = []
    instance.add_middleware(GatewayAuthMiddleware,
        settings=GatewayCrossCuttingSettings(CPEDGE_EDGE_PROXY=enabled))
    @instance.api_route('/{path:path}', methods=['POST', 'GET', 'DELETE', 'PUT'])
    def owner_stub(request: Request, path: str):
        instance.state.forwarded.append((request.headers.get('authorization'),
                                        request.state.tenant_id, request.state.jwt_claims))
        # Forwarding must preserve the owner's rejection of an unknown token.
        return JSONResponse({'detail': 'owner denied unknown bot'}, status_code=403)
    return instance


@pytest.mark.parametrize('operation', ['heartbeat', 'claim', 'complete'])
@pytest.mark.parametrize('enabled', [True, False])
def test_only_agent_posts_reach_the_owner_without_manufacturing_claims(monkeypatch, operation, enabled):
    instance = app(monkeypatch, enabled)
    path = f'/api/v1/hypermesh/bots/{BOT}/agent/{operation}'
    assert bot_agent_route(path, 'POST')
    with TestClient(instance) as client:
        response = client.post(path, headers={'Authorization': 'Bearer ' + TOKEN, 'X-Tenant-ID': TENANT})
    assert response.status_code == (403 if enabled else 401)
    assert instance.state.forwarded == ([('Bearer ' + TOKEN, uuid.UUID(TENANT), None)] if enabled else [])


@pytest.mark.parametrize('method,path', [
    ('POST', '/api/v1/hypermesh/bots'), ('GET', '/api/v1/hypermesh/bots'),
    ('POST', f'/api/v1/hypermesh/bots/{BOT}/assignment'),
    ('POST', f'/api/v1/hypermesh/bots/{BOT}/control'),
    ('POST', f'/api/v1/hypermesh/bots/{BOT}/tasks'),
    ('POST', f'/api/v1/hypermesh/bots/{BOT}/agent/claim/extra'),
    ('POST', '/api/v1/hypermesh/bots/not-a-uuid/agent/claim'),
    ('GET', f'/api/v1/hypermesh/bots/{BOT}/agent/claim'),
    ('DELETE', f'/api/v1/hypermesh/bots/{BOT}/agent/claim'),
    ('POST', '/api/v1/hypermesh/site/jobs'),
    ('POST', '/api/v1/hypermesh/leases'), ('POST', '/graphql'),
])
def test_bot_token_cannot_authorize_owner_host_or_other_methods(monkeypatch, method, path):
    instance = app(monkeypatch)
    assert not bot_agent_route(path, method)
    with TestClient(instance) as client:
        response = client.request(method, path, headers={'Authorization': 'Bearer ' + TOKEN, 'X-Tenant-ID': TENANT})
    assert response.status_code == 401
    assert not instance.state.forwarded


@pytest.mark.parametrize('token,tenant', [
    (TOKEN, ''), (TOKEN, 'invalid'), ('hm_bot_short', TENANT),
    ('hm_bot_' + 'g' * 64, TENANT), ('hm_dev_' + 'a' * 64, TENANT),
    ('hm_site_fake', TENANT), ('', TENANT),
])
def test_agent_forwarding_requires_token_shape_and_tenant(monkeypatch, token, tenant):
    instance = app(monkeypatch)
    with TestClient(instance) as client:
        response = client.post(f'/api/v1/hypermesh/bots/{BOT}/agent/heartbeat',
            headers={'Authorization': 'Bearer ' + token, 'X-Tenant-ID': tenant})
    assert response.status_code == 401
    assert not instance.state.forwarded
