from __future__ import annotations

import uuid

import pytest

from api.infrastructure.security.tenant_session_jwt import mint_tenant_session_jwt
from controlplane_edge.auth_utils import resolve_bearer_claims, resolve_bearer_claims_sync


@pytest.mark.asyncio
async def test_gateway_accepts_tenant_session_jwt():
    tid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    token = mint_tenant_session_jwt(
        claims={"sub": "u1", "email": "chris@fyberlabs.com", "azp": "controlplane-m2m"},
        tenant_id=tid,
        extra_roles=["admin"],
    )
    claims = await resolve_bearer_claims(token)
    assert claims is not None
    assert claims["tenant_id"] == str(tid)
    assert claims["panopticon_auth"] == "tenant_session"
    sync = resolve_bearer_claims_sync(token)
    assert sync is not None
    assert sync["https://panopticon.dev/tenant_id"] == str(tid)
