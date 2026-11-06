"""Native closure tokens are accepted only at these exact realm-global actions."""
from __future__ import annotations

import json
import os

from controlplane_identity.security.keycloak_jwt import get_keycloak_jwt_validator
from jwt import InvalidTokenError, PyJWKClientError

_ROUTES = {
    ("POST", "/api/v1/me/account-closure"),
    ("POST", "/api/v1/operator/account-closures"),
    ("GET", "/api/v1/operator/account-closures"),
    ("POST", "/api/v1/operator/account-closures/hold"),
}


def closure_route(path: str, method: str) -> bool:
    return (method, path.rstrip("/")) in _ROUTES


async def closure_claims(token: str, path: str) -> dict | None:
    try:
        validator = get_keycloak_jwt_validator()
        if path.rstrip("/") == "/api/v1/me/account-closure":
            claims = await validator.validate(token)
            subject = claims.get("sub")
            if (not isinstance(subject, str) or not subject.strip() or len(subject) > 512
                    or subject.startswith("apikey:") or claims.get("spanopticon_auth")
                    or claims.get("purpose") or "api_key_id" in claims or "key_id" in claims):
                return None
            return claims
        clients = json.loads(os.environ.get("ACCOUNT_CLOSURE_OPERATOR_CLIENT_IDS", "[]"))
        if (not isinstance(clients, list) or not clients or len(clients) > 1000
                or any(not isinstance(value, str) or not value.strip() for value in clients)
                or len(set(clients)) != len(clients)):
            return None
        return await validator.validate_closure_operator(token, client_ids=frozenset(clients))
    except (InvalidTokenError, PyJWKClientError, ValueError, TypeError):
        return None
