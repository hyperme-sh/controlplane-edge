import json
import pytest
from controlplane_edge.operator_routes import configured_route, signed_delivery
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


def test_signed_operator_routes_require_one_valid_exact_declaration(monkeypatch, tmp_path):
    route = {'method': 'POST', 'path': PATH, 'signature_header': 'example-signature', 'max_body_bytes': 4096}
    monkeypatch.delenv('EDGE_OPERATOR_ROUTES_FILE', raising=False)
    for rows in ([route, route], [route | {'signature_header': 'authorization'}],
                 [route | {'max_body_bytes': True}], [route | {'max_body_bytes': (1 << 20) + 1}]):
        monkeypatch.setenv('EDGE_OPERATOR_ROUTES_JSON', json.dumps({'signed': rows}))
        assert not is_public_path(PATH, 'POST')
    monkeypatch.setenv('EDGE_OPERATOR_ROUTES_JSON', json.dumps({'signed': [route]}))
    assert is_public_path(PATH, 'POST')
    assert signed_delivery(PATH, 'POST').max_body_bytes == 4096
    assert not is_public_path(PATH + '/', 'POST')
    assert not is_public_path(PATH, 'GET')
    file = tmp_path / 'routes.json'
    file.write_text(json.dumps({'signed': [route]}))
    monkeypatch.setenv('EDGE_OPERATOR_ROUTES_FILE', str(file))
    assert not is_public_path(PATH, 'POST')
