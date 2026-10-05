"""Validate setup credentials only on the endpoints owned by host setup."""
from __future__ import annotations

import re

from api.core.config import settings
from api.infrastructure.security.keycloak_jwt import get_keycloak_jwt_validator
from api.infrastructure.security.tenant_session_jwt import try_decode_host_setup_session

_DEVICE_ROUTES = {
    ("GET", "/auth/host-setup/me"),
    ("POST", "/auth/host-setup/enrollment/grant"),
    ("POST", "/auth/host-setup/session"),
}
_REGISTRATION = "/api/v1/hypermesh/host-registrations"
_REQUEST = re.compile(r"^" + _REGISTRATION + r"/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}(?P<complete>/complete)?$")


def session_route(path: str, method: str) -> bool:
    if method == "POST" and path in {
        _REGISTRATION,
        "/api/v1/hypermesh/host-onboarding/approve-activation",
        "/api/v1/hypermesh/host-onboarding/approve-resume",
    }:
        return True
    match = _REQUEST.fullmatch(path)
    return bool(match and method == ("POST" if match.group("complete") else "GET"))


async def resolve_setup_claims(token: str, path: str, method: str) -> dict | None:
    path = path.rstrip("/") or "/"
    method = method.upper()
    if (method, path) in _DEVICE_ROUTES:
        if not settings.keycloak_jwks_url or not settings.keycloak_issuer:
            return None
        try:
            return await get_keycloak_jwt_validator().validate_host_setup(token)
        except Exception:
            return None
    if session_route(path, method):
        return try_decode_host_setup_session(token)
    return None
