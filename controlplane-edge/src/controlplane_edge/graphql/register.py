"""Mount ``/graphql`` on the controlplane FastAPI app."""

from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI, Request
from strawberry.fastapi import GraphQLRouter

from api.core.config import settings as api_settings
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
        if api_settings.keycloak_jwks_url and api_settings.keycloak_issuer:
            try:
                from api.infrastructure.security.keycloak_jwt import get_keycloak_jwt_validator

                claims = await get_keycloak_jwt_validator().validate(token)
                user_sub = str(claims.get("sub") or "") or None
            except Exception as exc:  # noqa: BLE001
                logger.debug("GraphQL JWT fallback: %s", exc)
                user_sub = None
        if user_sub is None and token:
            try:
                import jwt as pyjwt

                payload = pyjwt.decode(
                    token,
                    options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
                )
                user_sub = str(payload.get("sub") or "") or None
            except Exception:
                user_sub = None

    agg = OpenAPIAggregationSettings()
    ctx = GraphQLContext(
        authorization=auth,
        tenant_id=tenant_id,
        user_sub=user_sub,
        settings=agg,
        http=_shared_http(),
    )
    ctx.loaders = build_loaders(ctx)
    return ctx


def register_graphql_routes(app: FastAPI) -> None:
    router = GraphQLRouter(schema, context_getter=get_graphql_context)
    app.include_router(router, prefix="/graphql")
    logger.info("GraphQL mounted at /graphql")
