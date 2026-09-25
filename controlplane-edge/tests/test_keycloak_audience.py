"""Keycloak tokens must present an allowed audience. azp alone is not enough."""

from __future__ import annotations

import pytest
from jwt import InvalidTokenError

from api.core.config import settings
from api.infrastructure.security import keycloak_jwt as kc


def test_allowed_audiences_include_account_and_clients():
    allowed = settings.keycloak_allowed_audience_set()
    assert "account" in allowed
    assert "controlplane-frontend" in allowed
    assert "hypermesh-native" in settings.keycloak_allowed_azp_set()
    assert settings.keycloak_allowed_azp_set() <= allowed


def test_hypermesh_native_stays_allowed_when_the_env_list_omits_it(monkeypatch):
    monkeypatch.setattr(settings, "keycloak_allowed_client_ids", "controlplane-frontend")
    assert "hypermesh-native" in settings.keycloak_allowed_azp_set()
    assert "hypermesh-native" in settings.keycloak_allowed_audience_set()


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
