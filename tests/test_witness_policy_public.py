"""Only the public signed-policy GET passes the gateway, with anonymous limits."""
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
import respx

from controlplane_edge.rate_limiter import TenantUserRateLimiter
from controlplane_edge.public_paths import is_public_path
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting

PATH = '/api/v1/acl/sociacl/witness-policy'


@pytest.mark.parametrize('method,path', [('POST', PATH), ('PUT', PATH), ('DELETE', PATH),
                                         ('HEAD', PATH), ('GET', PATH + '/'),
                                         ('GET', PATH + '/install'), ('GET', PATH + '-admin'),
                                         ('GET', '/api/v1/acl/sociacl/recovery')])
def test_public_policy_exemption_is_exact(method, path):
    assert not is_public_path(path, method)


@pytest.mark.parametrize('upstream_status', [200, 404, 503])
@respx.mock
def test_public_policy_proxy_and_no_store_headers(monkeypatch, upstream_status):
    monkeypatch.setenv('CPEDGE_ACL_SERVICE_URL', 'http://acl.edge.test')
    monkeypatch.setenv('CPEDGE_RATE_LIMIT_PER_MINUTE', '5000')
    app = FastAPI()
    register_gateway_cross_cutting(app)
    app.state.gateway_rate_limiter = TenantUserRateLimiter(per_minute=2)
    body = {'type': 'sociacl-witness-policy-envelope-v1', 'payload': 'exact', 'signature': 'exact'}
    upstream = respx.get('http://acl.edge.test' + PATH).mock(
        return_value=httpx.Response(upstream_status, json=body, headers={'Cache-Control': 'no-store'}))
    assert is_public_path(PATH, 'GET')
    with TestClient(app) as client:
        for _ in range(2):
            response = client.get(PATH, headers={'X-Tenant-ID': str(uuid.uuid4())})
            assert response.status_code == upstream_status
            assert response.json() == body
            assert response.headers['cache-control'] == 'no-store'
        assert client.get(PATH, headers={'X-Tenant-ID': str(uuid.uuid4())}).status_code == 429
        assert client.post(PATH).status_code == 401
        assert client.get(PATH + '/install').status_code == 401
    assert upstream.call_count == 2
