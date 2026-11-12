"""Paths that skip mandatory JWT at the gateway policy layer."""

from __future__ import annotations

import re

from controlplane_api.config import settings

from controlplane_edge.edge_settings import versions_access_mode
from controlplane_edge.public_hypermesh_agent import is_public_hypermesh_agent
from controlplane_edge.public_hypermesh_browse import is_public_hypermesh_browse


def is_versions_path(path: str, method: str = "GET") -> bool:
    """Exact GET /versions. The peer summary, not /version and not a prefix."""

    normalized = path.rstrip("/") or "/"
    return method.upper() == "GET" and normalized == "/versions"


_MACHINE_IDENTITY_ROUTES = frozenset(
    (
        ("POST", "/api/v1/aiuditor/machine/renew"),
        ("POST", "/api/v1/hypermesh/agent/identity/bind"),
        ("POST", "/api/v1/hypermesh/agent/identity/token"),
        ("POST", "/api/v1/hypermesh/agent/identity/contract-token"),
        ("GET", "/api/v1/hypermesh/agent/identity/configuration"),
        ("GET", "/api/v1/hypermesh/agent/identity/authorities"),
    )
)


def is_machine_identity_path(path: str, method: str = "POST") -> bool:
    """Anonymous machine identity routes. Public, but still rate limited."""

    normalized = path.rstrip("/") or "/"
    return (method.upper(), normalized) in _MACHINE_IDENTITY_ROUTES


def is_issuer_session_end_path(path: str, method: str = "POST") -> bool:
    """Exact issuer-session fence. Payment verifies the original browser credential."""

    normalized = path.rstrip("/") or "/"
    return (
        method.upper() == "POST"
        and normalized == "/api/v1/payments/connect/access-session/end"
    )


def is_witness_policy_path(path: str, method: str = "GET") -> bool:
    """Public signed policy only; no prefix or write-method exemption."""
    return method.upper() == "GET" and path == "/api/v1/acl/sociacl/witness-policy"


def is_contact_lane_path(path: str, method: str = "GET") -> bool:
    """Opaque ciphertext lanes only; never a broad SociACL authentication bypass."""
    return method.upper() in {"GET", "POST"} and re.fullmatch(
        r"/api/v1/acl/sociacl/(?:contact-lanes|first-contact)/[0-9a-f]{64}/messages", path
    ) is not None


def is_sumsub_webhook_path(path: str, method: str) -> bool:
    return method == "POST" and path in {
        "/api/v1/verification/webhooks/sumsub/sandbox/applicant-deleted",
        "/api/v1/verification/webhooks/sumsub/sandbox/review-events",
    }


def is_public_path(path: str, method: str = "GET") -> bool:
    """Docs, health, OpenAPI aggregation, static assets; GraphQL GET (playground) optional."""

    if path in ("/",):
        return False
    if is_witness_policy_path(path, method) or is_sumsub_webhook_path(path, method) or is_contact_lane_path(path, method):
        return True
    from controlplane_edge.operator_routes import configured_route
    if configured_route("public", path, method):
        return True
    path = path.rstrip("/") or "/"
    if is_public_hypermesh_browse(path, method):
        return True
    # AIuditor verifies the bound machine proof; this is not a browser JWT.
    if method.upper() == "POST" and path == "/api/v1/aiuditor/machine/renew":
        return True
    if is_public_hypermesh_agent(path, method):
        return True
    if path.startswith("/graphql") and method == "GET":
        return True
    if path.startswith("/changelog/openapi"):
        return True
    # GitHub OIDC is not a Keycloak or tenant-session JWT. The auth
    # service verifies it. Allow this one method and path, not a prefix
    # and not GET.
    if method.upper() == "POST" and path == "/auth" + settings.smoke_session_route:
        return True
    if method.upper() == "GET" and path == "/auth/enrollment/marketplace":
        return True
    # Build identity for this process. GET only, exact path.
    if method.upper() == "GET" and path == "/version":
        return True
    # Peer summary. public and off skip the session JWT (off returns 404).
    # authenticated stays on the gateway auth middleware. The rate limiter
    # still sees this path; see GatewayRateLimitMiddleware.
    if is_versions_path(path, method):
        return versions_access_mode() != "authenticated"
    # Sign-out may have only the original browser credential. Payment verifies
    # it. Exact POST, not a prefix, and still rate limited.
    if is_issuer_session_end_path(path, method):
        return True
    # Extracted-service surfaces that must work without a session JWT
    # (OIDC start/callback/refresh).
    edge_public = (
        "/auth/login",
        "/auth/callback",
        "/auth/refresh",
    )
    if any(path == p or path.startswith(p + "/") for p in edge_public):
        return True
    prefixes = (
        "/api/v1/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/v1/openapi.json",
        "/v1/docs",
        "/v2/openapi.json",
        "/v2/docs",
        "/assets",
    )
    if any(path.startswith(pref) for pref in prefixes):
        return True
    if path in ("/favicon.ico", "/robots.txt"):
        return True
    return False
