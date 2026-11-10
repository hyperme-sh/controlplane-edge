"""Unit tests for OpenAPI merge and changelog diff."""

from __future__ import annotations

from controlplane_edge.openapi_merge import diff_openapi_changelog, merge_openapi


def test_merge_prefixes_remote_paths_and_tags():
    edge_spec = {
        "openapi": "3.0.0",
        "info": {"title": "G", "version": "1"},
        "paths": {"/api/v1/ping": {"get": {"tags": ["Health"], "responses": {"200": {"description": "ok"}}}}},
        "components": {"schemas": {"Ping": {"type": "object"}}},
    }
    auth_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Auth", "version": "1"},
        "paths": {
            "/auth/login": {
                "get": {
                    "tags": ["auth"],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
        "components": {"schemas": {"User": {"type": "object", "properties": {"id": {"type": "string"}}}}},
    }
    merged = merge_openapi(
        [("controlplane-edge", edge_spec), ("auth", auth_spec)],
        title="Test",
        version="1.0.0",
    )
    assert "/api/v1/ping" in merged["paths"]
    assert "/_upstream/auth/auth/login" in merged["paths"]
    op = merged["paths"]["/_upstream/auth/auth/login"]["get"]
    assert op["tags"] == ["[auth] auth"]
    assert "Ping" in merged["components"]["schemas"]
    assert "auth__User" in merged["components"]["schemas"]


def test_diff_openapi_changelog_paths_and_schemas():
    a = {
        "paths": {"/a": {}, "/b": {}},
        "components": {"schemas": {"S1": {}, "S2": {}}},
    }
    b = {
        "paths": {"/b": {}, "/c": {}},
        "components": {"schemas": {"S2": {}, "S3": {}}},
    }
    d = diff_openapi_changelog(a, b)
    assert d["paths_added"] == ["/c"]
    assert d["paths_removed"] == ["/a"]
    assert "S3" in d["schemas_added"]
    assert "S1" in d["schemas_removed"]


def _oauth_spec(url, *, inherited=True):
    doc = {'openapi': '3.0.3', 'info': {'title': 'Owner', 'version': '1'},
        'components': {'securitySchemes': {'OAuth': {'type': 'oauth2', 'flows': {
            'clientCredentials': {'tokenUrl': url, 'scopes': {'read': 'Read'}}}}}},
        'paths': {'/private': {'get': {'responses': {'200': {'description': 'ok'}}}},
                  '/public': {'get': {'security': [], 'responses': {'200': {'description': 'ok'}}}}}}
    if inherited:doc['security'] = [{'OAuth': ['read']}, {}]
    else:doc['paths']['/private']['get']['security'] = [{'OAuth': ['read']}]
    return doc


def test_colliding_oauth_schemes_rewrite_explicit_and_inherited_requirements():
    from copy import deepcopy
    from openapi_spec_validator import validate
    first = _oauth_spec('https://issuer-one.example/token')
    second = _oauth_spec('https://issuer-two.example/token', inherited=False)
    third = _oauth_spec('https://issuer-three.example/token')
    snapshot = deepcopy([first, second, third])
    merged = merge_openapi([('controlplane-edge', first), ('auth', second), ('user', third)])
    assert merged['paths']['/private']['get']['security'] == [{'OAuth': ['read']}, {}]
    assert merged['paths']['/_upstream/auth/private']['get']['security'] == [{'auth_OAuth': ['read']}]
    assert merged['paths']['/_upstream/user/private']['get']['security'] == [{'user_OAuth': ['read']}, {}]
    assert merged['paths']['/_upstream/user/public']['get']['security'] == []
    assert merged['components']['securitySchemes']['auth_OAuth']['flows']['clientCredentials']['tokenUrl'] == 'https://issuer-two.example/token'
    assert [first, second, third] == snapshot
    validate(merged)


def test_security_rename_avoids_preexisting_prefixed_names_and_rewrites_callbacks():
    first = _oauth_spec('https://one.example/token')
    first['components']['securitySchemes']['auth_OAuth'] = {'type': 'http', 'scheme': 'bearer'}
    second = _oauth_spec('https://two.example/token')
    second['paths']['/private']['post'] = {'responses': {'200': {'description': 'ok'}},
        'callbacks': {'notify': {'{$request.body#/callback}': {'post': {
            'security': [{'OAuth': ['read']}], 'responses': {'200': {'description': 'ok'}}}}}}}
    merged = merge_openapi([('controlplane-edge', first), ('auth', second)])
    schemes = merged['components']['securitySchemes']
    assert schemes['auth_OAuth'] == {'type': 'http', 'scheme': 'bearer'}
    assert schemes['auth_OAuth_2']['flows']['clientCredentials']['tokenUrl'] == 'https://two.example/token'
    path = merged['paths']['/_upstream/auth/private']
    assert path['get']['security'] == [{'auth_OAuth_2': ['read']}, {}]
    assert path['post']['callbacks']['notify']['{$request.body#/callback}']['post']['security'] == [{'auth_OAuth_2': ['read']}]


def test_scheme_aliases_and_natural_prefixed_keys_do_not_collide_or_rewrite_examples():
    first = _oauth_spec('https://one.example/token')
    second = _oauth_spec('https://two.example/token')
    second['components']['securitySchemes']['auth_OAuth'] = {'$ref': '#/components/securitySchemes/OAuth'}
    example = {'security': [{'OAuth': ['payload-only']}]}
    second['components']['schemas'] = {'Payload': {'type': 'object', 'example': example}}
    second['paths']['/private']['get']['security'] = [{'OAuth': ['read'], 'auth_OAuth': []}]
    merged = merge_openapi([('controlplane-edge', first), ('auth', second)])
    schemes = merged['components']['securitySchemes']
    assert schemes['auth_OAuth'] == {'$ref': '#/components/securitySchemes/auth_OAuth_2'}
    assert schemes['auth_OAuth_2']['flows']['clientCredentials']['tokenUrl'] == 'https://two.example/token'
    assert merged['paths']['/_upstream/auth/private']['get']['security'] == [{'auth_OAuth_2': ['read'], 'auth_OAuth': []}]
    assert merged['components']['schemas']['auth__Payload']['example'] == example


def test_discriminated_schema_refs_and_bare_names_stay_with_their_owner():
    from copy import deepcopy
    literal = {'$ref': '#/components/schemas/BudgetTokens',
               'discriminator': {'mapping': {'budget': '#/components/schemas/BudgetTokens'}}}
    union = {'oneOf': [{'$ref': '#/components/schemas/BudgetTokens'}],
             'discriminator': {'propertyName': 'kind', 'mapping': {
                 'pointer': '#/components/schemas/BudgetTokens', 'bare': 'BudgetTokens',
                 'external': 'https://example.test/types.json#/BudgetTokens'}}}
    spec = {'openapi': '3.1.0', 'info': {'title': 'owner', 'version': '1'},
            'paths': {'/grants': {'post': {'requestBody': {'content': {'application/json': {
                'schema': union, 'example': literal, 'examples': {'literal': {'value': literal}}}}},
                'responses': {'200': {'description': 'ok'}}}}},
            'components': {'schemas': {'BudgetTokens': {'type': 'object'}, 'Grant': {
                'type': 'object', 'properties': {'asks': {'type': 'array', 'items': union},
                    'value': {'$ref': '#/components/schemas/BudgetTokens'}},
                'example': literal, 'default': literal, 'enum': [literal], 'x-literal': literal}}}}
    original = deepcopy(spec)
    merged = merge_openapi([('hypermesh', spec), ('other', spec)])
    assert spec == original
    for owner in ('hypermesh', 'other'):
        grant = merged['components']['schemas'][owner + '__Grant']
        mapping = grant['properties']['asks']['items']['discriminator']['mapping']
        ref = '#/components/schemas/' + owner + '__BudgetTokens'
        assert mapping == {'pointer': ref, 'bare': ref, 'external': 'https://example.test/types.json#/BudgetTokens'}
        assert grant['properties']['asks']['items']['oneOf'] == [{'$ref': ref}]
        assert grant['properties']['value']['$ref'] == ref
        assert grant['example'] == grant['default'] == grant['x-literal'] == literal
        assert grant['enum'] == [literal]
        media = merged['paths']['/_upstream/' + owner + '/grants']['post']['requestBody']['content']['application/json']
        assert media['schema']['discriminator']['mapping'] == mapping
        assert media['example'] == literal and media['examples']['literal']['value'] == literal


def test_inline_parameter_response_and_recursive_schema_discriminators_are_namespaced():
    schema = {'oneOf': [{'$ref': '#/components/schemas/Node'}],
              'discriminator': {'propertyName': 'kind', 'mapping': {'node': 'Node'}}}
    spec = {'openapi': '3.1.0', 'info': {'title': 'Owner', 'version': '1'},
            'components': {'schemas': {'Node': {'type': 'object', 'additionalProperties': schema}}},
            'paths': {'/nodes': {'parameters': [{'name': 'filter', 'in': 'query', 'schema': schema}],
                'get': {'responses': {'200': {'description': 'ok', 'content': {
                    'application/json': {'schema': schema}}}}}}}}
    merged = merge_openapi([('owner', spec)])
    ref = '#/components/schemas/owner__Node'
    path = merged['paths']['/_upstream/owner/nodes']
    for found in [path['parameters'][0]['schema'],
                  path['get']['responses']['200']['content']['application/json']['schema'],
                  merged['components']['schemas']['owner__Node']['additionalProperties']]:
        assert found['oneOf'] == [{'$ref': ref}]
        assert found['discriminator']['mapping'] == {'node': ref}
