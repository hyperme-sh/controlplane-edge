"""Shared JWT resolution for gateway HTTP and gRPC (Keycloak or dev unverified)."""

from __future__ import annotations

import logging
from typing import Any

from controlplane_api.config import settings as api_settings

logger = logging.getLogger(__name__)


async def resolve_bearer_claims(token: str) -> dict[str, Any] | None:
    """Return JWT claims or None if invalid."""
    if not token:
        return None
    from api.infrastructure.security.api_key_exchange_jwt import try_decode_api_key_session_jwt
    from api.infrastructure.security.tenant_session_jwt import try_decode_tenant_session_jwt

    ex = try_decode_api_key_session_jwt(token)
    if ex is not None:
        return ex
    switched = try_decode_tenant_session_jwt(token)
    if switched is not None:
        return switched
    if api_settings.keycloak_jwks_url and api_settings.keycloak_issuer:
        try:
            from api.infrastructure.security.keycloak_jwt import get_keycloak_jwt_validator

            return await get_keycloak_jwt_validator().validate(token)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Keycloak JWT validation failed: %s", exc)
            return None
    # No Keycloak: decode without verify (local dev / tests)
    try:
        import jwt as pyjwt

        claims = pyjwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
        )
        if claims.get("azp") == "hypermesh-host-setup" or claims.get("purpose") == "host_setup":
            return None
        return claims
    except Exception as exc:  # noqa: BLE001
        logger.debug("Bearer decode failed: %s", exc)
        return None


def resolve_bearer_claims_sync(token: str) -> dict[str, Any] | None:
    """Sync JWT resolution for gRPC servicers (no running asyncio loop)."""
    if not token:
        return None
    from api.infrastructure.security.api_key_exchange_jwt import try_decode_api_key_session_jwt
    from api.infrastructure.security.tenant_session_jwt import try_decode_tenant_session_jwt

    ex = try_decode_api_key_session_jwt(token)
    if ex is not None:
        return ex
    switched = try_decode_tenant_session_jwt(token)
    if switched is not None:
        return switched
    if api_settings.keycloak_jwks_url and api_settings.keycloak_issuer:
        try:
            from api.infrastructure.security.keycloak_jwt import get_keycloak_jwt_validator

            return get_keycloak_jwt_validator().validate_sync(token)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Keycloak JWT validation failed: %s", exc)
            return None
    try:
        import jwt as pyjwt

        claims = pyjwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
        )
        if claims.get("azp") == "hypermesh-host-setup" or claims.get("purpose") == "host_setup":
            return None
        return claims
    except Exception as exc:  # noqa: BLE001
        logger.debug("Bearer decode failed: %s", exc)
        return None
