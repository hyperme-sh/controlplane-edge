"""Prefix matching for the gateway edge cutover (no HTTP)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from controlplane_edge.edge_routes import (
    LOCKED_MONOLITH_CHECKOUT_PREFIXES,
    MONOLITH_COMPAT_PREFIXES,
    match_edge_route,
    path_matches_prefix,
)


@pytest.mark.parametrize(
    ("path", "prefix", "expected"),
    [
        ("/api/v1/users", "/api/v1/users", True),
        ("/api/v1/users/", "/api/v1/users", True),
        ("/api/v1/users/abc", "/api/v1/users", True),
        ("/api/v1/users-export", "/api/v1/users", False),
        ("/api/v1/ai/inference", "/api/v1/ai/inference", True),
        ("/api/v1/ai/models", "/api/v1/ai/inference", False),
        ("/auth/login", "/auth", True),
        ("/authorize", "/auth", False),
    ],
)
def test_path_matches_prefix_boundary(path: str, prefix: str, expected: bool) -> None:
    assert path_matches_prefix(path, prefix) is expected


def _urls(**overrides: str | None) -> SimpleNamespace:
    base = dict(
        auth_service_url=None,
        user_service_url=None,
        payment_service_url=None,
        acl_service_url=None,
        marketplace_service_url=None,
        ai_service_url=None,
        api_keys_service_url=None,
        template_service_url=None,
        tennessee_windage_service_url=None,
        hypermesh_service_url=None,
        hypermesh_gateway_service_url=None,
        aiuditor_service_url=None,
        turn_service_url=None,
        oracles_service_url=None,
        payments_service_url=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_extracted_prefixes_match_configured_upstreams() -> None:
    settings = _urls(
        auth_service_url="http://auth.example",
        user_service_url="http://user.example",
        payment_service_url="http://pay.example",
        acl_service_url="http://acl.example",
        marketplace_service_url="http://mkt.example",
        ai_service_url="http://ai.example",
        api_keys_service_url="http://keys.example",
        template_service_url="http://tpl.example",
        tennessee_windage_service_url="http://tw.example",
        hypermesh_service_url="http://hm.example",
        hypermesh_gateway_service_url="http://hmr.example",
        aiuditor_service_url="http://aiuditor.example",
        turn_service_url="http://turn.example",
        oracles_service_url="http://oracles.example",
        payments_service_url="http://payments.example",
    )
    cases = {
        "/auth/me": ("auth", "http://auth.example"),
        "/api/v1/users": ("user", "http://user.example"),
        "/api/v1/users/11111111-1111-1111-1111-111111111111/assign_role": (
            "user",
            "http://user.example",
        ),
        "/api/v1/groups": ("user", "http://user.example"),
        "/api/v1/organizations/abc": ("user", "http://user.example"),
        "/api/v1/acl/policies": ("acl", "http://acl.example"),
        "/api/v1/acl/sociacl/shares": ("acl", "http://acl.example"),
        "/api/v1/payments/billing-records": ("payment", "http://pay.example"),
        "/api/v1/payments/v0/intent": ("payments", "http://payments.example"),
        "/api/v1/payments/v0/receipt": ("payments", "http://payments.example"),
        "/api/v1/budgets": ("payment", "http://pay.example"),
        "/api/v1/marketplace/listings": ("marketplace", "http://mkt.example"),
        "/api/v1/ai/inference": ("ai", "http://ai.example"),
        "/api/v1/ai/complete": ("ai", "http://ai.example"),
        "/api/v1/ai/usage/history": ("ai", "http://ai.example"),
        "/api/v1/api-keys": ("api_keys", "http://keys.example"),
        "/api/v1/samples": ("template", "http://tpl.example"),
        "/api/v1/tw/missions": ("tennessee_windage", "http://tw.example"),
        "/api/v1/turn/allocate": ("turn", "http://turn.example"),
        "/api/v1/oracles/v0/attest": ("oracles", "http://oracles.example"),
        "/api/v1/aiuditor/connections": ("aiuditor", "http://aiuditor.example"),
        "/api/v1/aiuditor/catalog": ("aiuditor", "http://aiuditor.example"),
        "/api/v1/aiuditor/catalog/cccccccc-cccc-4ccc-8ccc-cccccccccc01/allocate": (
            "aiuditor",
            "http://aiuditor.example",
        ),
        "/api/v1/aiuditor/contracts/eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee/grant": (
            "aiuditor",
            "http://aiuditor.example",
        ),
        "/api/v1/hypermesh/leases": ("hypermesh", "http://hm.example"),
        "/api/v1/hypermesh/site/jobs": ("hypermesh", "http://hm.example"),
        "/api/v1/hypermesh/site/devices/a6400000-0640-4000-8000-000000000001": (
            "hypermesh",
            "http://hm.example",
        ),
        "/api/v1/auditor/v0/tickets": ("hypermesh", "http://hm.example"),
        "/api/v1/grants/v0/grants": ("hypermesh", "http://hm.example"),
    }
    for path, (service_id, base) in cases.items():
        match = match_edge_route(path, settings)
        assert match is not None, path
        assert match.service_id == service_id
        assert match.base_url == base


def test_hypermesh_gateway_is_never_proxied() -> None:
    """The prompt chokepoint must not depend on this control plane being up.

    Configuring its URL is for merging its spec into /openapi.json, not for
    forwarding renter traffic through here.
    """

    settings = _urls(
        hypermesh_service_url="http://hm.example",
        hypermesh_gateway_service_url="http://hmr.example",
    )
    for path in (
        "/api/v1/hypermesh-gateway",
        "/api/v1/hypermesh-gateway/v1/chat/completions",
        "/api/v1/hypermesh-gateway/v1/ir/receipts",
        "/api/v1/hypermesh-gateway/tunnels/apply",
    ):
        assert match_edge_route(path, settings) is None, path


def test_aiuditor_does_not_wrap_sibling_products() -> None:
    """TURN / oracles / payments stay on their prefixes. Catalog is AIuditor."""

    settings = _urls(
        aiuditor_service_url="http://aiuditor.example",
        turn_service_url="http://turn.example",
        oracles_service_url="http://oracles.example",
        payments_service_url="http://payments.example",
    )
    siblings = {
        "/api/v1/turn/allocate": "turn",
        "/api/v1/oracles/v0/attest": "oracles",
        "/api/v1/payments/v0/intent": "payments",
        "/api/v1/payments/v0/receipt": "payments",
    }
    for path, service_id in siblings.items():
        match = match_edge_route(path, settings)
        assert match is not None, path
        assert match.service_id == service_id
        assert match.service_id != "aiuditor"
    catalog = match_edge_route("/api/v1/aiuditor/catalog", settings)
    assert catalog is not None
    assert catalog.service_id == "aiuditor"


def test_aiuditor_prefix_does_not_steal_site_inbox() -> None:
    """/api/v1/auditor is fyber.auditor on hypermesh. /api/v1/aiuditor is AIuditor."""

    settings = _urls(
        hypermesh_service_url="http://hm.example",
        aiuditor_service_url="http://aiuditor.example",
    )
    inbox = match_edge_route("/api/v1/auditor/v0/tickets", settings)
    assert inbox is not None
    assert inbox.service_id == "hypermesh"
    grant = match_edge_route("/api/v1/aiuditor/connections", settings)
    assert grant is not None
    assert grant.service_id == "aiuditor"


def test_monolith_leftovers_are_not_proxied() -> None:
    settings = _urls(
        user_service_url="http://user.example",
        ai_service_url="http://ai.example",
        payment_service_url="http://pay.example",
    )
    leftovers = [
        "/api/v1/tenants",
        "/api/v1/tenants/11111111-1111-1111-1111-111111111111",
        "/api/v1/roles/",
        "/api/v1/account/me",
        "/api/v1/dashboard",
        "/api/v1/app_configuration",
        "/api/v1/billing",
        "/api/v1/products",
        "/api/v1/invoices",
        "/api/v1/ai/set_model_preference/llama",
        "/api/v1/ai/models",
        "/api/v1/ai/ask",
        "/api/v1/health",
        "/api/v1/internal/validate",
    ]
    for path in leftovers:
        assert match_edge_route(path, settings) is None, path


def test_compat_prefixes_are_not_edge_owned() -> None:
    for leftover in MONOLITH_COMPAT_PREFIXES:
        assert match_edge_route(leftover) is None, leftover


def test_locked_checkout_prefixes_are_not_proxied() -> None:
    settings = _urls(payment_service_url="http://pay.example")
    for prefix in LOCKED_MONOLITH_CHECKOUT_PREFIXES:
        assert match_edge_route(prefix, settings) is None


def test_product_route_manifests_keep_existing_prefixes():
    import json
    from pathlib import Path
    from controlplane_edge import edge_routes
    bundle = json.loads(Path(edge_routes.__file__).with_name('product_routes.json').read_text())
    declarations = {entry['prefix']:(entry['service_id'], entry['url_attr'])
                    for product in bundle.values() for entry in product['edge_routes']}
    routes = {route.prefix:(route.service_id, route.url_attr) for route in edge_routes.EDGE_ROUTES}
    assert declarations.items() <= routes.items()
    for prefix in ('/api/v1/hypermesh', '/api/v1/auditor', '/api/v1/grants'):
        assert declarations[prefix] == ('hypermesh', 'hypermesh_service_url')
    assert bundle['hypermesh-gateway']['edge_routes'] == []


def test_product_manifest_cannot_claim_another_service(monkeypatch):
    import json
    from pathlib import Path
    from controlplane_edge import edge_routes
    bundle = json.loads(Path(edge_routes.__file__).with_name('product_routes.json').read_text())
    bundle['hypermesh']['edge_routes'][0]['service_id'] = 'user'
    monkeypatch.setattr(edge_routes.Path, 'read_text', lambda self: json.dumps(bundle))
    with pytest.raises(ValueError, match='owner service'):
        edge_routes._product_routes()


def test_portal_controls_uses_user_service() -> None:
    match = match_edge_route("/api/v1/me/portal-controls", _urls(user_service_url="http://user.example"))
    assert match is not None
    assert match.service_id == "user"
    assert match.base_url == "http://user.example"
