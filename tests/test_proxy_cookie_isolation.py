import httpx
import pytest
from fastapi import FastAPI
from types import SimpleNamespace
from controlplane_edge.edge_proxy import EdgeProxyMiddleware, _proxy_client
from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings


@pytest.mark.asyncio
async def test_shared_client_never_replays_another_callers_cookie():
    seen = []
    async def upstream(request):
        seen.append(request.headers.get('cookie'))
        return httpx.Response(200, headers={'set-cookie': 'session=alice; Path=/'}, content=b'ok')
    app = FastAPI()
    app.add_middleware(EdgeProxyMiddleware,
        settings=OpenAPIAggregationSettings(CPEDGE_AUTH_SERVICE_URL='https://auth.example'),
        cross=SimpleNamespace(edge_proxy_enabled=True, proxy_timeout_s=5))
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as shared:
        app.state.edge_proxy_client = shared
        for cookie in [None, None, 'session=bob', None]:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://edge.example') as caller:
                response = await caller.get('/auth/login', headers={} if cookie is None else {'Cookie': cookie})
                assert response.status_code == 200
                assert response.headers['set-cookie'] == 'session=alice; Path=/'
    assert seen == [None, None, 'session=bob', None]


def test_owned_proxy_client_rejects_cookie_storage():
    client = _proxy_client(httpx.Timeout(5))
    request = httpx.Request('GET', 'https://auth.example/')
    response = httpx.Response(200, headers={'set-cookie': 'session=alice; Path=/'}, request=request)
    client.cookies.extract_cookies(response)
    assert not list(client.cookies.jar)
