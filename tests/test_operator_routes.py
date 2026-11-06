import json
import pytest
from controlplane_edge.operator_routes import configured_route
from controlplane_edge.public_paths import is_public_path


PATH = '/api/v1/payments/operator/webhook'


def test_operator_exceptions_are_default_closed(monkeypatch):
    monkeypatch.delenv('EDGE_OPERATOR_ROUTES_FILE', raising=False)
    assert not is_public_path(PATH, 'POST')
    assert not configured_route('retired', PATH)


def test_operator_exemption_is_exact_method_and_path(monkeypatch, tmp_path):
    p = tmp_path/'routes.json'
    p.write_text(json.dumps({'public': [{'method': 'POST', 'path': PATH}]}))
    monkeypatch.setenv('EDGE_OPERATOR_ROUTES_FILE', str(p))
    assert is_public_path(PATH, 'POST')
    for path, method in [(PATH, 'GET'), (PATH+'/', 'POST'), (PATH+'/extra', 'POST')]:
        assert not is_public_path(path, method)


@pytest.mark.parametrize('document', ['{', '[]', '{"public": "all"}',
    '{"public":[{"method":"POST","path":"/api/v1/users"}]}',
    '{"public":[{"method":"POST","path":"/api/v1/payments/../users"}]}'])
def test_invalid_operator_configuration_grants_no_exemption(monkeypatch, tmp_path, document):
    p = tmp_path/'routes.json'; p.write_text(document)
    monkeypatch.setenv('EDGE_OPERATOR_ROUTES_FILE', str(p))
    assert not configured_route('public', PATH, 'POST')
