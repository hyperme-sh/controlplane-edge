"""Path prefixes the gateway reverse-proxies to extracted services.

This is a mount-less edge: the gateway process does **not** import microservice
routers. Matching is prefix + path-boundary (``/api/v1/users`` matches
``/api/v1/users/…`` but not ``/api/v1/users-export``).

AI is split on purpose: ai-service owns ``/inference``, ``/complete``, and
``/usage``; the monolith chat leftover (``/models``, ``/ask``,
``/set_model_preference``, sessions) stays on the gateway.

Do not invent new public paths here — only forward surfaces that already exist
on auth / user / acl / payment / marketplace / ai / api-keys / template /
tennessee-windage / hypermesh / turn / oracles / payments / fyber.auditor / fyber.privilege_grant.

The hypermesh gateway is deliberately absent. It is the only chokepoint that
sees prompts, and it must keep serving a paid ticket while this control plane
is down, so nothing here may put the gateway on its path. Renters reach it on
its own hostname. Its spec is still merged into ``/openapi.json``.
"""

from __future__ import annotations

from dataclasses import dataclass

from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings


@dataclass(frozen=True)
class EdgeRoute:
    """One existing service surface, keyed by URL path prefix."""

    prefix: str
    service_id: str
    url_attr: str


@dataclass(frozen=True)
class EdgeMatch:
    prefix: str
    service_id: str
    base_url: str | None


# Longest prefixes first so ``/api/v1/ai/inference`` wins over a future ``/api/v1/ai``.
EDGE_ROUTES: tuple[EdgeRoute, ...] = (
    EdgeRoute("/auth", "auth", "auth_service_url"),
    EdgeRoute("/api/v1/users", "user", "user_service_url"),
    EdgeRoute("/api/v1/groups", "user", "user_service_url"),
    EdgeRoute("/api/v1/organizations", "user", "user_service_url"),
    EdgeRoute("/api/v1/acl", "acl", "acl_service_url"),
    EdgeRoute("/api/v1/payments/v0", "payments", "payments_service_url"),
    EdgeRoute("/api/v1/payments", "payment", "payment_service_url"),
    EdgeRoute("/api/v1/budgets", "payment", "payment_service_url"),
    EdgeRoute("/api/v1/marketplace", "marketplace", "marketplace_service_url"),
    EdgeRoute("/api/v1/ai/inference", "ai", "ai_service_url"),
    EdgeRoute("/api/v1/ai/complete", "ai", "ai_service_url"),
    EdgeRoute("/api/v1/ai/usage", "ai", "ai_service_url"),
    EdgeRoute("/api/v1/api-keys", "api_keys", "api_keys_service_url"),
    EdgeRoute("/api/v1/samples", "template", "template_service_url"),
    EdgeRoute("/api/v1/tw", "tennessee_windage", "tennessee_windage_service_url"),
    EdgeRoute("/api/v1/turn", "turn", "turn_service_url"),
    EdgeRoute("/api/v1/oracles", "oracles", "oracles_service_url"),
    EdgeRoute("/api/v1/hypermesh", "hypermesh", "hypermesh_service_url"),
    EdgeRoute("/api/v1/auditor", "hypermesh", "hypermesh_service_url"),
    EdgeRoute("/api/v1/grants", "hypermesh", "hypermesh_service_url"),
)

# Still served by controlplane-core on the gateway. Not proxied.
# See docs/controlplane-edge-cutover.md.
MONOLITH_COMPAT_PREFIXES: tuple[str, ...] = (
    "/api/v1/tenants",
    "/api/v1/roles",
    "/api/v1/account",
    "/api/v1/dashboard",
    "/api/v1/app_configuration",
    "/api/v1/billing",
    "/api/v1/configurations",
    "/api/v1/checkouts",
    "/api/v1/products",
    "/api/v1/invoices",
    "/api/v1/prices",
    "/api/v1/health",
    "/api/v1/features",
    "/api/v1/brandings",
    "/api/v1/storage",
    "/api/v1/permissions",
    "/api/v1/security",
    "/api/v1/notifications",
    "/api/v1/audit-logs",
    "/api/v1/ssos",
    "/api/v1/ai/models",
    "/api/v1/ai/history",
    "/api/v1/ai/new_session",
    "/api/v1/ai/sessions",
    "/api/v1/ai/set_model_preference",
    "/api/v1/ai/ask",
)

# P0-D F: lock leftover monolith checkout on the test/prod edge.
# Canonical cash is payment-service /api/v1/payments/stripe/checkout-sessions.
LOCKED_MONOLITH_CHECKOUT_PREFIXES: tuple[str, ...] = (
    "/api/v1/checkouts",
)


def locked_monolith_checkout_path(path: str) -> bool:
    return any(path_matches_prefix(path, prefix) for prefix in LOCKED_MONOLITH_CHECKOUT_PREFIXES)


def path_matches_prefix(path: str, prefix: str) -> bool:
    """True when ``path`` is ``prefix`` or a child of ``prefix`` (boundary-safe)."""

    norm_path = path.split("?", 1)[0]
    if not norm_path:
        norm_path = "/"
    if len(norm_path) > 1:
        norm_path = norm_path.rstrip("/")
    norm_prefix = prefix.rstrip("/") or "/"
    return norm_path == norm_prefix or norm_path.startswith(norm_prefix + "/")


def match_edge_route(
    path: str,
    settings: OpenAPIAggregationSettings | object | None = None,
) -> EdgeMatch | None:
    """Return the first (longest) edge route that owns ``path``, or None."""

    settings = settings or OpenAPIAggregationSettings()
    ranked = sorted(EDGE_ROUTES, key=lambda r: len(r.prefix), reverse=True)
    for route in ranked:
        if not path_matches_prefix(path, route.prefix):
            continue
        raw = getattr(settings, route.url_attr)
        base = str(raw).rstrip("/") if raw else None
        if raw is not None and not str(raw).strip():
            base = None
        return EdgeMatch(prefix=route.prefix, service_id=route.service_id, base_url=base)
    return None
