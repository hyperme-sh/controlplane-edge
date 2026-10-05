"""Keycloak tokens must present an allowed audience. azp alone is not enough."""

from __future__ import annotations

from pathlib import Path

import pytest
from jwt import InvalidTokenError

from api.core.config import Settings, settings
from api.infrastructure.security import keycloak_jwt as kc


def test_allowed_audiences_include_account_and_clients():
    allowed = settings.keycloak_allowed_audience_set()
    assert "account" in allowed
    assert "controlplane-frontend" in allowed
    assert settings.keycloak_allowed_azp_set() <= allowed


def test_default_allow_list_includes_hypermesh_native():
    default = Settings.model_fields["keycloak_allowed_client_ids"].default
    assert "hypermesh-native" in default.split(",")
    assert "hypermesh-host-setup" not in default.split(",")
    # s3r.ch backup OAuth is not a control-plane API client.
    assert "s3rch-web" not in default.split(",")


def test_operator_revokes_hypermesh_native_by_omitting_it_from_env(monkeypatch):
    monkeypatch.setattr(settings, "keycloak_allowed_client_ids", "controlplane-frontend")
    assert "hypermesh-native" not in settings.keycloak_allowed_azp_set()
    assert "hypermesh-native" not in settings.keycloak_allowed_audience_set()
    assert "hypermesh-host-setup" not in settings.keycloak_allowed_azp_set()
    assert "hypermesh-host-setup" not in settings.keycloak_allowed_audience_set()


def test_empty_audience_set_is_rejected(monkeypatch):
    class _Key:
        key = "unused"

    class _Jwks:
        def get_signing_key_from_jwt(self, token: str):
            return _Key()

    validator = kc.KeycloakJWTValidator(
        jwks_url="http://jwks.example/certs",
        issuer="http://kc.example/realms/controlplane",
        client_id="",
    )
    validator._jwks_client = _Jwks()
    monkeypatch.setattr(settings, "keycloak_allowed_audience_set", lambda: frozenset())
    with pytest.raises(InvalidTokenError, match="no allowed Keycloak audiences"):
        validator.validate_sync("header.payload.sig")


def test_vm_example_allowlist_matches_defaults_and_excludes_host_setup():
    root = Path(__file__).resolve().parents[2]
    assignments = dict(
        line.split("=", 1) for line in (root / ".env.vm.example").read_text().splitlines()
        if line.startswith("KEYCLOAK_ALLOWED_CLIENT_IDS=")
    )
    explicit = assignments["KEYCLOAK_ALLOWED_CLIENT_IDS"]
    default = Settings.model_fields["keycloak_allowed_client_ids"].default
    assert set(explicit.split(",")) == set(default.split(","))
    vm = settings.model_copy(update={"keycloak_allowed_client_ids": explicit})
    assert "hypermesh-host-setup" not in vm.keycloak_allowed_azp_set()
    assert "hypermesh-host-setup" not in vm.keycloak_allowed_audience_set()
