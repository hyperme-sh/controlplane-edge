"""Paths that skip mandatory JWT at the gateway policy layer."""

from __future__ import annotations

from controlplane_edge.public_hypermesh_agent import is_public_hypermesh_agent
from controlplane_edge.public_hypermesh_browse import is_public_hypermesh_browse


def is_public_path(path: str, method: str = "GET") -> bool:
    """Docs, health, OpenAPI aggregation, static assets; GraphQL GET (playground) optional."""

    if path in ("/",):
        return False
    path = path.rstrip("/") or "/"
    if is_public_hypermesh_browse(path, method):
        return True
    if is_public_hypermesh_agent(path, method):
        return True
    if path.startswith("/graphql") and method == "GET":
        return True
    if path.startswith("/changelog/openapi"):
        return True
    # Extracted-service surfaces that must work without a session JWT
    # (OIDC start/callback/refresh; Stripe webhook).
    edge_public = (
        "/auth/login",
        "/auth/callback",
        "/auth/refresh",
        # GitHub OIDC is not a Keycloak or tenant-session JWT. The auth
        # service verifies it. The edge must not reject it first.
        "/auth/hypermesh-smoke/session",
        "/api/v1/payments/stripe/webhook",
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
