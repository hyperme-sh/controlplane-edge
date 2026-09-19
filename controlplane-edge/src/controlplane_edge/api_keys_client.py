"""HTTP client for api-keys-service internal validation.

Re-exported from controlplane-core so the gateway and the hypermesh router
share one implementation of this check.
"""

from __future__ import annotations

from api.infrastructure.externals.api_keys_client import validate_api_key_remote

__all__ = ["validate_api_key_remote"]
