"""HTTP client for api-keys-service internal validation.

Re-exported from controlplane-core so the control-plane edge and the hypermesh gateway
share one implementation of this check.
"""

from __future__ import annotations

from controlplane_identity.api_keys_client import validate_api_key_remote

__all__ = ["validate_api_key_remote"]
