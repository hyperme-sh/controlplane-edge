import httpx
import pytest
from controlplane_edge import closure_auth
from controlplane_edge.middleware.policy import GatewayAuthMiddleware
from fastapi import FastAPI, Request
from jwt import InvalidTokenError


@pytest.fixture
def native_validator(monkeypatch):
    calls = []
    class Validator:
        async def validate(self, token):
            calls.append(("native", token))
            if token != "human":
                raise InvalidTokenError()
            return {"sub": "human-subject"}
        async def validate_closure_operator(self, token, *, client_ids):
            calls.append(("operator", token, client_ids))
            if token != "ai":
                raise InvalidTokenError()
            return {"sub": "ai-subject"}
    monkeypatch.setenv("ACCOUNT_CLOSURE_OPERATOR_CLIENT_IDS", '["specific-ai"]')
    monkeypatch.setattr(closure_auth, "get_keycloak_jwt_validator", Validator)
    return calls


@pytest.mark.parametrize("path,method,token", [
    ("/api/v1/me/account-closure", "POST", "human"),
    ("/api/v1/operator/account-closures", "POST", "ai"),
    ("/api/v1/operator/account-closures", "GET", "ai"),
    ("/api/v1/operator/account-closures/hold", "POST", "ai"),
])
async def test_dedicated_native_tokens_reach_exact_closure_routes(native_validator, monkeypatch, path, method, token):
    async def generic(*args):
        pytest.fail("closure authority must not enter generic token or API key exchange")
    monkeypatch.setattr("controlplane_edge.middleware.policy.resolve_bearer_claims", generic)
    monkeypatch.setattr("controlplane_edge.middleware.policy.validate_api_key_remote", generic)
    app = FastAPI()
    app.add_middleware(GatewayAuthMiddleware)
    async def endpoint(request: Request):
        return {"subject": request.state.user_sub, "tenant": request.state.tenant_id}
    app.add_api_route(path, endpoint, methods=[method])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        good = await client.request(method, path, headers={"Authorization": "Bearer " + token})
        assert good.status_code == 200 and good.json()["tenant"] is None
        for headers in [{}, {"Authorization": "Bearer wrapped"}, {"X-Api-Key": "key"},
                        {"Authorization": "Bearer hm_site_opaque"}]:
            bad = await client.request(method, path, headers=headers)
            assert bad.status_code == 401
    if token == "ai":
        assert native_validator[0] == ("operator", "ai", frozenset({"specific-ai"}))


@pytest.mark.parametrize("path,method", [
    ("/api/v1/operator/account-closures-extra", "POST"),
    ("/api/v1/operator/account-closures/other", "POST"),
    ("/api/v1/operator/account-closures", "DELETE"),
    ("/api/v1/me/account-closure-request", "POST"),
    ("/api/v1/me/account-closure", "GET"),
])
def test_closure_token_trust_does_not_expand_to_other_routes(path, method):
    assert not closure_auth.closure_route(path, method)


@pytest.mark.parametrize("config", ['[]', '{}', '["specific-ai", "specific-ai"]', '[1]', 'broken'])
async def test_no_default_or_malformed_operator_trust(native_validator, monkeypatch, config):
    monkeypatch.setenv("ACCOUNT_CLOSURE_OPERATOR_CLIENT_IDS", config)
    assert await closure_auth.closure_claims("ai", "/api/v1/operator/account-closures") is None
    assert native_validator == []


@pytest.mark.parametrize('method,path,token,body', [
    ('POST','/api/v1/me/account-closure','human',{'confirmation':'CLOSE MY ACCOUNT'}),
    ('POST','/api/v1/operator/account-closures','ai',{'confirmation':'CLOSE MY ACCOUNT','subject':'target'}),
    ('GET','/api/v1/operator/account-closures?subject=target','ai',None),
    ('POST','/api/v1/operator/account-closures/hold','ai',{'subject':'target','hold':True,'reference':'owned-fixture'}),
])
async def test_installed_user_proxy_receives_only_original_native_authority(native_validator, monkeypatch, method, path, token, body):
    from user_service import closure_proxy
    from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting
    original = httpx.AsyncClient
    observed = []
    def upstream(request):
        observed.append(request)
        return httpx.Response(202, json={'state':'closing'})
    user_app = FastAPI()
    user_app.include_router(closure_proxy.router, prefix='/api/v1')
    monkeypatch.setenv('CPEDGE_USER_SERVICE_URL','http://user.fixture')
    monkeypatch.setenv('CPEDGE_EDGE_PROXY','true')
    app = FastAPI()
    register_gateway_cross_cutting(app)
    await app.state.edge_proxy_client.aclose()
    user_requests = []
    async def user_transport(request):
        user_requests.append(request)
        return await httpx.ASGITransport(app=user_app).handle_async_request(request)
    edge_client = original(transport=httpx.MockTransport(user_transport))
    app.state.edge_proxy_client = edge_client
    monkeypatch.setenv('ACCOUNT_CLOSURE_ACTIONS_ENABLED','true')
    monkeypatch.setenv('ACCOUNT_CLOSURE_ENFORCEMENT_ENABLED','true')
    monkeypatch.setenv('ACCOUNT_CLOSURE_AUTHORITY_URL','https://private.fixture')
    monkeypatch.setattr(closure_proxy.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(upstream),**kwargs))
    async with edge_client, original(transport=httpx.ASGITransport(app=app),base_url='http://edge') as client:
        result = await client.request(method,path,
            headers={'Authorization':'Bearer '+token,'X-Tenant-ID':'spoofed','X-Actor-ID':'other'},json=body)
    assert result.status_code == 202
    user_request, = user_requests
    assert user_request.url.host == 'user.fixture'
    assert user_request.headers['authorization'] == 'Bearer '+token
    assert 'x-tenant-id' not in user_request.headers
    request, = observed
    assert request.headers['authorization'] == 'Bearer '+token
    assert request.url.path == path.split('?')[0]
    if method == 'GET':
        assert request.url.params['subject'] == 'target'
    assert not any(name in request.headers for name in ('x-tenant-id','x-actor-id','x-account-lifecycle-token'))


@pytest.mark.parametrize('async_mode',[False,True])
async def test_enforcement_cannot_fall_back_to_unverified_development_claims(monkeypatch, async_mode):
    import jwt
    from controlplane_api.config import settings
    from controlplane_edge.auth_utils import resolve_bearer_claims, resolve_bearer_claims_sync
    monkeypatch.setenv('ACCOUNT_CLOSURE_ENFORCEMENT_ENABLED','true')
    monkeypatch.setattr(settings,'keycloak_jwks_url','')
    monkeypatch.setattr(settings,'keycloak_issuer','')
    token = jwt.encode({'sub':'unverified','tenant_id':'00000000-0000-0000-0000-000000000001'},'fixture-secret-at-least-32-characters',algorithm='HS256')
    if async_mode:
        assert await resolve_bearer_claims(token) is None
    else:
        assert resolve_bearer_claims_sync(token) is None


@pytest.mark.parametrize('path', ['/api/v1/internal/account-lifecycle/check',
    '/api/v1/hypermesh/internal/account-lifecycle/close-owner'])
@pytest.mark.parametrize('method', ['GET','POST','OPTIONS'])
async def test_private_authority_paths_are_never_public_gateway_routes(path, method):
    app = FastAPI()
    app.add_middleware(GatewayAuthMiddleware)
    async def forbidden():
        pytest.fail('Private authority reached a public edge handler')
    app.add_api_route(path, forbidden, methods=[method])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://edge') as client:
        result = await client.request(method,path,headers={'Authorization':'Bearer native-looking'})
    assert result.status_code == 404
