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
