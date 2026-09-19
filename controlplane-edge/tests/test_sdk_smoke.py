"""Smoke: generated OpenAPI artifact is compatible with merged gateway spec shape."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SDK_SPEC = REPO / "sdk" / "openapi" / "v1" / "openapi.json"


@pytest.mark.skipif(not SDK_SPEC.is_file(), reason="sdk/openapi/v1/openapi.json not present")
def test_sdk_openapi_json_is_openapi_document() -> None:
    data = json.loads(SDK_SPEC.read_text(encoding="utf-8"))
    assert "openapi" in data
    assert "paths" in data
    assert "info" in data
