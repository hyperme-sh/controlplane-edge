"""Mount ``/graphql`` on the controlplane FastAPI app."""

from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI, Request
from strawberry.fastapi import GraphQLRouter

from controlplane_api.config import settings as api_settings
from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
from controlplane_edge.graphql.context import GraphQLContext
from controlplane_edge.graphql.dataloaders import build_loaders
from controlplane_edge.graphql.schema import schema

logger = logging.getLogger(__name__)

_http_singleton: httpx.AsyncClient | None = None


def _shared_http() -> httpx.AsyncClient:
    global _http_singleton
    if _http_singleton is None:
        _http_singleton = httpx.AsyncClient(timeout=30.0)
    return _http_singleton


async def _verified_bearer_claims(token: str) -> dict | None:
    """Honor a bound JWT or Keycloak. Never an unsigned decode."""

    if not token:
        return None
    try:
        from controlplane_identity.security.tenant_session_jwt import (
            try_decode_tenant_session_jwt,
        )
    except Exception:
        try_decode_tenant_session_jwt = None
    if try_decode_tenant_session_jwt is not None:
        session = try_decode_tenant_session_jwt(token)
        if session:
            return session
    try:
        from controlplane_identity.security.api_key_exchange_jwt import (
            try_decode_api_key_session_jwt,
        )
    except Exception:
        try_decode_api_key_session_jwt = None
    if try_decode_api_key_session_jwt is not None:
        exchanged = try_decode_api_key_session_jwt(token)
        if exchanged:
            return exchanged
    if api_settings.keycloak_jwks_url and api_settings.keycloak_issuer:
        try:
            from controlplane_identity.security.keycloak_jwt import get_keycloak_jwt_validator

            return await get_keycloak_jwt_validator().validate(token)
        except Exception as exc:  # noqa: BLE001
            logger.debug("GraphQL JWT rejected: %s", exc)
    return None


async def get_graphql_context(request: Request) -> GraphQLContext:
    auth = request.headers.get("Authorization")
    tenant_id = getattr(request.state, "tenant_id", None)
    user_sub = getattr(request.state, "user_sub", None)
    claims = getattr(request.state, "jwt_claims", None)
    # Header is a cross-check only when the edge policy has not bound a
    # credential. If policy ran and left tenant unset, do not take the header.
    if tenant_id is None and claims is None:
        tid_raw = request.headers.get("x-tenant-id") or request.headers.get("X-Tenant-ID")
        if tid_raw:
            try:
                import uuid

                tenant_id = uuid.UUID(str(tid_raw).strip())
            except ValueError:
                tenant_id = None
    if user_sub is None and auth and auth.startswith("Bearer "):
        token = auth[7:].strip()
        verified = await _verified_bearer_claims(token)
        if verified:
            user_sub = str(verified.get("sub") or "") or None

    agg = OpenAPIAggregationSettings()
    ctx = GraphQLContext(
        authorization=auth,
        tenant_id=tenant_id,
        user_sub=user_sub,
        settings=agg,
        http=getattr(getattr(request.scope.get("app"), "state", None), "graphql_http", None) or _shared_http(),
    )
    ctx.loaders = build_loaders(ctx)
    return ctx


def register_graphql_routes(app: FastAPI) -> None:
    router = GraphQLRouter(schema, context_getter=get_graphql_context)
    app.include_router(router, prefix="/graphql")
    logger.info("GraphQL mounted at /graphql")
