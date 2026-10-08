"""Tests for scripts/sdk-gen: OpenAPI export, retries, breaking detection, REST codegen wiring."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from panopticon_sdk_gen.breaking import (
    diff_openapi_structure,
    is_breaking_change,
    load_allowed_removals,
)
from panopticon_sdk_gen.export import (
    build_merged_openapi_offline,
    fetch_openapi_with_retry,
    merge_offline_with_existing,
    offline_export_is_incomplete,
    run_export_offline_sync,
    write_openapi_json,
)
from panopticon_sdk_gen.rest_codegen import (
    REST_PRESETS,
    run_openapi_generator_docker,
    sanitize_openapi_for_generator,
)

REPO = Path(__file__).resolve().parents[2]


def _minimal_openapi(paths: dict) -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "paths": paths,
        "components": {"schemas": {}},
    }


@pytest.mark.asyncio
async def test_offline_export_includes_openapi_key():
    doc = await build_merged_openapi_offline(version_label="v1")
    assert "openapi" in doc
    assert "paths" in doc


def test_fetch_openapi_retry_then_success(respx_mock: respx.MockRouter):
    url = "http://sdkgen.test/v1/openapi.json"
    spec = _minimal_openapi({"/x": {"get": {"responses": {"200": {"description": "ok"}}}}})
    route = respx_mock.get(url).mock(side_effect=[httpx.Response(503), httpx.Response(200, json=spec)])

    out = fetch_openapi_with_retry(url, max_retries=4, initial_backoff_s=0.01)
    assert out["openapi"] == "3.0.3"
    assert route.call_count == 2


def test_breaking_detects_removed_path():
    old = _minimal_openapi({"/a": {}, "/b": {}})
    new = _minimal_openapi({"/a": {}})
    breaking, detail = is_breaking_change(old, new)
    assert breaking is True
    assert "/b" in detail["paths_removed"]


def test_allowed_removal_is_not_breaking(tmp_path: Path):
    old = _minimal_openapi({"/a": {}, "/b": {}, "/c": {}})
    old["components"]["schemas"]["Gone"] = {"type": "object"}
    new = _minimal_openapi({"/a": {}})
    allowed_file = tmp_path / "allowed.json"
    allowed_file.write_text(json.dumps({"paths": ["/b"], "schemas": ["Gone"]}), encoding="utf-8")
    breaking, detail = is_breaking_change(old, new, load_allowed_removals(allowed_file))
    assert breaking is True
    assert detail["paths_removed"] == ["/c"]
    assert detail["paths_removed_allowed"] == ["/b"]
    assert detail["schemas_removed_allowed"] == ["Gone"]
    new["paths"]["/c"] = {}
    breaking, _d = is_breaking_change(old, new, load_allowed_removals(allowed_file))
    assert breaking is False
    assert load_allowed_removals(tmp_path / "missing.json") == {"paths": set(), "schemas": set()}


def test_committed_spec_has_no_allowed_removal_paths():
    root = Path(__file__).resolve().parents[2]
    allowed = load_allowed_removals(root / "sdk" / "openapi" / "v1" / "allowed-removals.json")
    spec = json.loads((root / "sdk" / "openapi" / "v1" / "openapi.json").read_text(encoding="utf-8"))
    assert not allowed["paths"] & set(spec["paths"])
    assert not allowed["schemas"] & set(spec["components"]["schemas"])


def test_breaking_ok_when_only_additions():
    old = _minimal_openapi({"/a": {}})
    new = _minimal_openapi({"/a": {}, "/c": {}})
    breaking, _d = is_breaking_change(old, new)
    assert breaking is False


def test_offline_export_incomplete_when_remotes_dropped():
    existing = _minimal_openapi({"/api/v1/account/me": {}, "/api/v1/acl/enforce": {}})
    stub = _minimal_openapi({"/export-health": {}})
    assert offline_export_is_incomplete(stub, existing) is True
    assert offline_export_is_incomplete(existing, existing) is False


def test_merge_offline_preserves_committed_and_skips_stub():
    existing = _minimal_openapi({"/api/v1/account/me": {}, "/api/v1/acl/enforce": {}})
    existing["components"]["schemas"]["AuthMeResponse"] = {"type": "object"}
    generated = _minimal_openapi(
        {
            "/export-health": {},
            "/api/v1/tw/missions": {"get": {"responses": {"200": {"description": "ok"}}}},
        }
    )
    generated["components"]["schemas"]["TwMission"] = {"type": "object"}
    merged = merge_offline_with_existing(existing, generated)
    assert "/api/v1/account/me" in merged["paths"]
    assert "/api/v1/acl/enforce" in merged["paths"]
    assert "/api/v1/tw/missions" in merged["paths"]
    assert "/export-health" not in merged["paths"]
    assert "AuthMeResponse" in merged["components"]["schemas"]
    assert "TwMission" in merged["components"]["schemas"]


def test_offline_export_sync_keeps_committed_spec(tmp_path: Path):
    existing = {
        "openapi": "3.1.0",
        "info": {"title": "Panopticon Control Plane API", "version": "1.0.0"},
        "paths": {
            "/api/v1/account/me": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/api/v1/acl/enforce": {"post": {"responses": {"200": {"description": "ok"}}}},
        },
        "components": {"schemas": {"AuthMeResponse": {"type": "object"}}},
    }
    out = tmp_path / "openapi.json"
    raw = json.dumps(existing, indent=2) + "\n"
    out.write_text(raw, encoding="utf-8")
    run_export_offline_sync(out)
    assert out.read_text(encoding="utf-8") == raw
    breaking, _d = is_breaking_change(existing, json.loads(out.read_text(encoding="utf-8")))
    assert breaking is False


def test_diff_openapi_structure_schema_removal():
    a = {"paths": {}, "components": {"schemas": {"Foo": {"type": "object"}}}}
    b = {"paths": {}, "components": {"schemas": {}}}
    d = diff_openapi_structure(a, b)
    assert "Foo" in d["schemas_removed"]


def test_rest_codegen_docker_invocation_smoke(tmp_path: Path):
    calls: list[list[str]] = []

    def fake_check_call(cmd, cwd, env):
        calls.append(cmd)

    spec_rel = Path("sdk/openapi/v1/openapi.json")
    out_rel = Path("sdk/rest/python")
    with patch("panopticon_sdk_gen.rest_codegen.subprocess.check_call", side_effect=fake_check_call):
        run_openapi_generator_docker(
            repo_root=REPO,
            spec_container_path="/local/" + spec_rel.as_posix(),
            generator="python",
            output_container_path="/local/" + out_rel.as_posix(),
            additional_properties=["library=urllib3"],
            docker_bin="docker",
        )
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "docker"
    assert "-g" in cmd and "python" in cmd
    assert any("/local/sdk/openapi/v1/openapi.json" in c for c in cmd)


def test_exported_openapi_fixture_contains_expected_keys():
    p = REPO / "sdk" / "openapi" / "v1" / "openapi.json"
    if not p.is_file():
        pytest.skip("sdk/openapi/v1/openapi.json not generated yet")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "openapi" in data and "paths" in data


def test_check_breaking_script_help():
    r = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "sdk-gen" / "check_breaking.py"), "-h"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "--baseline-file" in r.stdout


def test_rest_presets_include_all_target_languages():
    keys = set(REST_PRESETS.keys())
    assert {"typescript-fetch", "python", "kotlin", "swift5"} <= keys


def test_sanitize_openapi_rewrites_null_anyof():
    doc = {
        "openapi": "3.1.0",
        "components": {
            "schemas": {
                "Foo": {
                    "properties": {
                        "name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "nested": {
                            "anyOf": [
                                {"$ref": "#/components/schemas/Bar"},
                                {"type": "null"},
                            ]
                        },
                    }
                }
            }
        },
    }
    out = sanitize_openapi_for_generator(doc)
    name = out["components"]["schemas"]["Foo"]["properties"]["name"]
    assert name["type"] == "string"
    assert name["nullable"] is True
    assert "anyOf" not in name
    nested = out["components"]["schemas"]["Foo"]["properties"]["nested"]
    assert nested["nullable"] is True
    assert nested["allOf"] == [{"$ref": "#/components/schemas/Bar"}]
    assert "anyOf" not in nested
