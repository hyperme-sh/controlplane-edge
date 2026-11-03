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
