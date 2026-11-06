from __future__ import annotations

import pytest

from controlplane_api import config as api_config


@pytest.fixture(autouse=True)
def _api_key_exchange_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_config.settings,
        "api_key_exchange_jwt_secret",
        "test-api-key-exchange-secret-min-32-chars!!",
    )
    monkeypatch.setattr(
        api_config.settings, "api_keys_internal_token", "test-api-keys-internal-token"
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: local cross-protocol integration checks")


@pytest.fixture
def operator_payment_routes(monkeypatch, tmp_path):
    import json
    path = tmp_path / "operator-routes.json"
    path.write_text(json.dumps({
        "public": [{"method": "POST", "path": "/api/v1/payments/stripe/webhook"}],
        "retired": [{"method": "POST", "path": "/api/v1/payments/stripe/checkout-sessions"}],
    }))
    monkeypatch.setenv("EDGE_OPERATOR_ROUTES_FILE", str(path))
    return path
