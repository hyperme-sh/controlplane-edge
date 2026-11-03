"""Monolith /api/v1/checkouts and the removed card checkout route are 410 on the edge."""

from __future__ import annotations

from controlplane_edge.edge_routes import (
    LOCKED_MONOLITH_CHECKOUT_PREFIXES,
    locked_monolith_checkout_path,
)


def test_locked_prefixes_include_monolith_checkouts() -> None:
    assert "/api/v1/checkouts" in LOCKED_MONOLITH_CHECKOUT_PREFIXES


def test_locked_monolith_checkout_paths() -> None:
    assert locked_monolith_checkout_path("/api/v1/checkouts") is True
    assert locked_monolith_checkout_path("/api/v1/checkouts/") is True
    assert locked_monolith_checkout_path("/api/v1/checkouts/tenant/subscription") is True
    assert locked_monolith_checkout_path("/api/v1/checkouts/host/payment/success") is True
    assert locked_monolith_checkout_path("/api/v1/billing") is False
    assert locked_monolith_checkout_path("/api/v1/payments/stripe/checkout-sessions") is True
    assert locked_monolith_checkout_path("/api/v1/payments/usdc/lease-payments") is False
    assert locked_monolith_checkout_path("/api/v1/payments/stripe/webhook") is False
