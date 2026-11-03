"""Published API-key secrets must not mint or validate."""

from __future__ import annotations

import uuid

import pytest

from api.core import config as api_config
from api.infrastructure.externals.api_keys_client import validate_api_key_remote
from api.infrastructure.security.api_key_exchange_jwt import (
    mint_api_key_session_jwt,
    try_decode_api_key_session_jwt,
)
from api.infrastructure.security.tenant_session_jwt import (
    mint_tenant_session_jwt,
    try_decode_tenant_session_jwt,
)

TEST_SECRET = "test-api-key-exchange-secret-min-32-chars!!"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "dev-api-keys-internal-token",
        "dev-api-key-exchange-secret-change-in-production-min-32-chars!!",
    ],
)
def test_published_or_empty_exchange_secret_is_unusable(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setattr(api_config.settings, "api_key_exchange_jwt_secret", raw)
    assert api_config.settings.usable_api_key_exchange_secret() is None
    with pytest.raises(RuntimeError, match="API_KEY_EXCHANGE_JWT_SECRET"):
        mint_api_key_session_jwt(
            key_record_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            scopes=["renter"],
        )
    with pytest.raises(RuntimeError, match="API_KEY_EXCHANGE_JWT_SECRET"):
        mint_tenant_session_jwt(claims={"sub": "u"}, tenant_id=uuid.uuid4())
    assert try_decode_api_key_session_jwt("not.a.jwt") is None
    assert try_decode_tenant_session_jwt("not.a.jwt") is None


@pytest.mark.asyncio
async def test_empty_internal_token_does_not_call_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_config.settings, "api_keys_internal_token", "")
    assert api_config.settings.usable_api_keys_internal_token() is None
    assert (
        await validate_api_key_remote(
            base_url="http://api-keys.invalid",
            api_key="pref.secret",
            tenant_id=uuid.uuid4(),
        )
        is None
    )


def test_configured_secret_mints_and_decodes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_config.settings, "api_key_exchange_jwt_secret", TEST_SECRET)
    tenant = uuid.uuid4()
    token = mint_api_key_session_jwt(
        key_record_id=uuid.uuid4(),
        tenant_id=tenant,
        scopes=["renter"],
    )
    claims = try_decode_api_key_session_jwt(token)
    assert claims is not None
    assert claims["https://panopticon.dev/tenant_id"] == str(tenant)
