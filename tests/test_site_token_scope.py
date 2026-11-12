import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from controlplane_edge.middleware.policy import GatewayAuthMiddleware, site_token_route
from controlplane_edge.edge_settings import GatewayCrossCuttingSettings

ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'

@pytest.mark.parametrize('method,path', [
    ('GET','/versions'), ('POST','/graphql'), ('GET','/api/v1/account/me'),
    ('DELETE','/api/v1/hypermesh/site/jobs'),
    ('POST',f'/api/v1/auditor/v0/tickets/{ID}/resolve'),
    ('POST',f'/api/v1/grants/v0/grants/{ID}/revoke'),
    ('GET','/api/v1/hypermesh/site/devices/not-an-id'),
])
def test_forged_site_token_cannot_authorize_other_routes(monkeypatch, method, path):
    monkeypatch.setenv('EDGE_VERSIONS_ACCESS','authenticated')
    async def reject(token):
        return None
    monkeypatch.setattr('controlplane_edge.middleware.policy.resolve_bearer_claims', reject)
    app = FastAPI()
    app.add_middleware(GatewayAuthMiddleware)
    @app.api_route('/{rest:path}', methods=['GET','POST','DELETE'])
    def protected(rest):
        raise AssertionError('unauthenticated request reached protected handler')
    with TestClient(app) as client:
        response = client.request(method,path,headers={'Authorization':'Bearer hm_site_forged'})
    assert response.status_code == 401

@pytest.mark.parametrize('proxy_enabled', [True, False])
@pytest.mark.parametrize('method,path', [
    ('POST','/api/v1/hypermesh/site/jobs'),
    ('GET',f'/api/v1/hypermesh/site/jobs/{ID}'),
    ('GET',f'/api/v1/hypermesh/site/devices/{ID}'),
    ('POST','/api/v1/auditor/v0/tickets'),
    ('GET',f'/api/v1/auditor/v0/tickets/{ID}'),
    ('POST',f'/api/v1/auditor/v0/tickets/{ID}/ack'),
    ('GET','/api/v1/grants/v0/grants'),
    ('POST','/api/v1/grants/v0/grants'),
    ('GET',f'/api/v1/grants/v0/grants/{ID}'),
])
def test_site_allowlist_is_method_and_path_bounded(monkeypatch, method, path, proxy_enabled):
    assert site_token_route(path,method)
    assert not site_token_route(path+'/extra',method)
    assert not site_token_route(path, 'DELETE')
    async def reject(token):
        return None
    monkeypatch.setattr('controlplane_edge.middleware.policy.resolve_bearer_claims', reject)
    app = FastAPI()
    app.add_middleware(GatewayAuthMiddleware,
        settings=GatewayCrossCuttingSettings(CPEDGE_EDGE_PROXY=proxy_enabled))
    @app.api_route('/{rest:path}', methods=['GET', 'POST', 'DELETE'])
    def upstream_stub(rest):
        return {'accepted': True}
    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer hm_site_forged'}
        assert client.request(method, path, headers=headers).status_code == (200 if proxy_enabled else 401)
        assert client.request(method, path+'/extra', headers=headers).status_code == 401
        assert client.delete(path, headers=headers).status_code == 401


def test_site_passthrough_disabled_without_proxy(monkeypatch):
    async def reject(token):
        return None
    monkeypatch.setattr('controlplane_edge.middleware.policy.resolve_bearer_claims', reject)
    app = FastAPI()
    app.add_middleware(GatewayAuthMiddleware, settings=GatewayCrossCuttingSettings(CPEDGE_EDGE_PROXY=False))
    @app.post('/api/v1/hypermesh/site/jobs')
    def local_handler():
        raise AssertionError('opaque token reached local handler')
    with TestClient(app) as client:
        response = client.post('/api/v1/hypermesh/site/jobs', headers={'Authorization':'Bearer hm_site_forged'})
    assert response.status_code == 401
