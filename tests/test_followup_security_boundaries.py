"""Real edge/context regressions for credential, cookie and schema boundaries."""
import gzip
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from controlplane_edge.edge_proxy import EdgeProxyMiddleware
from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
from controlplane_edge.graphql.register import get_graphql_context
from controlplane_identity.security.api_key_exchange_jwt import (
    mint_api_key_session_jwt, try_decode_api_key_session_jwt,
)
from test_api_key_edge import cross_app  # noqa: F401


@pytest.mark.parametrize('original', [None, 'Bearer conflicting-original'])
async def test_graphql_prefers_policy_bound_identity(original):
    tenant, key = uuid.uuid4(), uuid.uuid4()
    token = mint_api_key_session_jwt(key_record_id=key, tenant_id=tenant, scopes=[])
    app = FastAPI()
    async with httpx.AsyncClient() as client:
        app.state.graphql_http = client
        request = Request({'type': 'http', 'method': 'POST', 'path': '/graphql',
            'headers': [] if original is None else [(b'authorization', original.encode())],
            'query_string': b'', 'app': app,
            'state': {'bearer_token': token, 'tenant_id': tenant,
                      'user_sub': 'apikey:' + str(key), 'jwt_claims': {'sub': 'apikey:' + str(key)}}})
        context = await get_graphql_context(request)
    assert context.authorization == 'Bearer ' + token
    assert context.tenant_id == tenant
    assert context.user_sub == 'apikey:' + str(key)


@respx.mock
def test_api_key_authenticates_tenant_users_and_forwards_exchanged_bearer(cross_app, monkeypatch):
    tenant, key = uuid.uuid4(), uuid.uuid4()
    validate = AsyncMock(return_value={'valid': True, 'key_id': str(key),
        'tenant_id': str(tenant), 'scopes': []})
    monkeypatch.setattr('controlplane_edge.middleware.policy.validate_api_key_remote', validate)
    upstream = respx.get('http://user.cc.test/api/v1/users').mock(return_value=httpx.Response(
        200, json={'items': [{'id': str(uuid.uuid4()), 'tenant_id': str(tenant),
                             'email': 'fixture@example.com'}]}))
    with TestClient(cross_app) as client:
        response = client.post('/graphql', json={'query': '{ tenantUsers { email } }'},
            headers={'X-Api-Key': 'fixture.raw-key', 'X-Tenant-ID': str(tenant)})
    assert response.status_code == 200
    assert 'errors' not in response.json(), response.json()
    assert response.json()['data']['tenantUsers'][0]['email'] == 'fixture@example.com'
    forwarded = upstream.calls.last.request.headers
    assert 'x-api-key' not in forwarded
    claims = try_decode_api_key_session_jwt(forwarded['authorization'].removeprefix('Bearer '))
    assert claims['sub'] == 'apikey:' + str(key)
    assert claims['https://spanopticon.dev/tenant_id'] == str(tenant)
    assert forwarded['x-tenant-id'] == str(tenant)


@respx.mock
def test_graphql_dual_credentials_still_rejected_before_exchange(cross_app, monkeypatch):
    validate = AsyncMock(side_effect=AssertionError('Ambiguous credentials reached validation'))
    monkeypatch.setattr('controlplane_edge.middleware.policy.validate_api_key_remote', validate)
    with TestClient(cross_app) as client:
        response = client.post('/graphql', json={'query': '{ tenantUsers { email } }'},
            headers={'X-Api-Key': 'fixture.key', 'Authorization': 'Bearer conflicting',
                     'X-Tenant-ID': str(uuid.uuid4())})
    assert response.status_code == 401
    validate.assert_not_awaited()


@pytest.mark.parametrize('cookies', [
    ['session=one; Path=/; HttpOnly', 'refresh=two; Expires=Wed, 21 Oct 2037 07:28:00 GMT; Path=/'],
    ['session=; Max-Age=0; Path=/', 'refresh=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/'],
])
async def test_proxy_preserves_individual_set_cookie_headers(cookies):
    body = gzip.compress(b'cookie-response')
    def upstream(request):
        return httpx.Response(200, headers=[('Set-Cookie', value) for value in cookies] +
            [('Content-Encoding', 'gzip'), ('Content-Length', str(len(body))),
             ('X-Owner-Detail', 'one'), ('X-Owner-Detail', 'two')], content=body)
    app = FastAPI()
    app.add_middleware(EdgeProxyMiddleware,
        settings=OpenAPIAggregationSettings(CPEDGE_AUTH_SERVICE_URL='https://auth.example'),
        cross=SimpleNamespace(edge_proxy_enabled=True, proxy_timeout_s=5))
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as shared:
        app.state.edge_proxy_client = shared
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://edge.example') as caller:
            response = await caller.get('/auth/callback')
    assert response.headers.get_list('set-cookie') == cookies
    assert response.headers.get_list('x-owner-detail') == ['one', 'two']
    assert response.content == b'cookie-response'
    assert 'content-encoding' not in response.headers
