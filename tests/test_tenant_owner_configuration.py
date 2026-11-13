"""The production entrypoint has no legacy startup or persistence dependency."""
import subprocess
import sys
import uuid

import httpx
import respx
from fastapi.testclient import TestClient
from controlplane_edge.main import create_app
from controlplane_identity.security.tenant_session_jwt import mint_tenant_session_jwt


def test_entrypoint_starts_without_legacy_or_database_imports():
    code = '''
import os, secrets
os.environ['API_KEY_EXCHANGE_JWT_SECRET'] = secrets.token_hex(24)
os.environ['API_KEYS_INTERNAL_TOKEN'] = secrets.token_hex(24)
import sys
class NoLegacy:
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'api', 'controlplane_db', 'controlplane_tenancy', 'sqlalchemy', 'asyncpg'}:
            raise AssertionError('Forbidden runtime import: ' + fullname)
sys.meta_path.insert(0, NoLegacy())
from fastapi.testclient import TestClient
from controlplane_edge.main import create_app
with TestClient(create_app()) as client:
    assert client.get('/api/v1/health/').status_code == 200
    assert client.get('/version').status_code == 200
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_prefixed_owner_used_without_host_database_lookup(monkeypatch):
    monkeypatch.setenv('CPEDGE_USER_SERVICE_URL', 'http://owner.fixture')
    monkeypatch.setenv('USER_SERVICE_URL', 'http://wrong.fixture')
    tenant = uuid.uuid4()
    token = mint_tenant_session_jwt(claims={'sub':'fixture-user'}, tenant_id=tenant)
    with respx.mock() as mock:
        route = mock.get('http://owner.fixture/api/v1/users').mock(return_value=httpx.Response(200, json=[]))
        with TestClient(create_app()) as client:
            response = client.get('/api/v1/users', headers={'Authorization': 'Bearer '+token, 'Host':'tenant.example'})
            assert response.status_code == 200
            assert route.calls[0].request.headers['x-tenant-id'] == str(tenant)
            assert client.get('/api/v1/roles', headers={'Authorization':'Bearer '+token}).status_code == 404


def test_standalone_http_metrics_record_requests(monkeypatch):
    from controlplane_api.metrics import HTTP_REQUESTS, HTTP_DURATION, HTTP_IN_FLIGHT, BUILD_INFO
    monkeypatch.setenv('GIT_SHA', 'a' * 40)
    count = HTTP_REQUESTS.labels(method='GET', route='/version', status='200')
    duration = HTTP_DURATION.labels(method='GET', route='/version')
    before, latency_before = count._value.get(), duration._sum.get()
    with TestClient(create_app()) as client:
        assert client.get('/version').status_code == 200
    assert count._value.get() == before + 1
    assert duration._sum.get() > latency_before
    assert HTTP_IN_FLIGHT._value.get() == 0
    assert BUILD_INFO.labels(git_sha='a' * 40, service='controlplane-edge')._value.get() == 1


def test_edge_rejects_local_database_metric_probe(monkeypatch):
    import pytest
    monkeypatch.setenv('METRICS_OUTBOX_PROBE', '1')
    with pytest.raises(ValueError, match='events owner'):
        create_app()
