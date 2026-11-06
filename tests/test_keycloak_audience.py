"""Keycloak tokens must present an allowed audience. azp alone is not enough."""

from __future__ import annotations

from pathlib import Path

import pytest
from jwt import InvalidTokenError

from controlplane_api.config import Settings, settings
from controlplane_identity.security import keycloak_jwt as kc


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

def _interactive_validator(monkeypatch, payload):
    import controlplane_identity.security.keycloak_jwt as impl

    class _Key:
        key = "unused"

    class _Jwks:
        headers = None

        def get_signing_key_from_jwt(self, token: str):
            return _Key()

    validator = kc.KeycloakJWTValidator("http://jwks.example/certs", "http://kc.example/realms/controlplane", "")
    validator._jwks_client = _Jwks()
    monkeypatch.setattr(impl.jwt, "decode", lambda *args, **kwargs: payload)
    monkeypatch.setattr(settings, "keycloak_allowed_audience_set", lambda: frozenset({"account"}))
    monkeypatch.setattr(
        settings,
        "keycloak_allowed_azp_set",
        lambda: frozenset({
            "controlplane-frontend",
            "controlplane-mobile",
            "controlplane-device",
            "controlplane-m2m",
            "controlplane-api-key",
            "hypermesh-native",
        }),
    )
    return validator


@pytest.mark.parametrize("azp", ["controlplane-mobile", "hypermesh-native", "controlplane-frontend", "controlplane-device"])
def test_interactive_token_without_age_confirmation_is_rejected(monkeypatch, azp):
    validator = _interactive_validator(monkeypatch, {"azp": azp, "sub": "person", "account_type": "human"})
    with pytest.raises(InvalidTokenError, match="age confirmation required"):
        validator.validate_sync("header.payload.sig")


@pytest.mark.parametrize("azp", ["controlplane-mobile", "hypermesh-native"])
def test_interactive_token_with_age_timestamp_is_accepted(monkeypatch, azp):
    validator = _interactive_validator(
        monkeypatch,
        {"azp": azp, "sub": "person", "account_type": "human", "terms_and_conditions": 1761900000},
    )
    assert validator.validate_sync("header.payload.sig")["azp"] == azp


def test_machine_and_service_tokens_do_not_need_an_age_timestamp(monkeypatch):
    machine = _interactive_validator(monkeypatch, {"azp": "controlplane-m2m", "sub": "service-account"})
    assert machine.validate_sync("header.payload.sig")["azp"] == "controlplane-m2m"
    automation = _interactive_validator(
        monkeypatch,
        {"azp": "hypermesh-native", "sub": "renter", "account_type": "service"},
    )
    assert automation.validate_sync("header.payload.sig")["account_type"] == "service"
