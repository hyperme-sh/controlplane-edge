"""Async HTTP calls to user, marketplace, acl, ai services — forwards Authorization + X-Tenant-ID."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from controlplane_edge.graphql.context import GraphQLContext


def _headers(ctx: GraphQLContext) -> dict[str, str]:
    h: dict[str, str] = {}
    if ctx.authorization:
        h["Authorization"] = ctx.authorization
    if ctx.tenant_id is not None:
        h["X-Tenant-ID"] = str(ctx.tenant_id)
    return h


def page_items(data: Any) -> list[dict[str, Any]]:
    """Extract ``items`` from a ``Page`` body (``UserListPage``, usage history, listings)."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []


async def fetch_users_json(
    ctx: GraphQLContext,
    *,
    limit: int = 50,
    offset: int = 0,
    q: str | None = None,
) -> list[dict[str, Any]]:
    base = ctx.settings.user_service_url
    if not base:
        raise RuntimeError("USER_SERVICE_URL / CPEDGE_USER_SERVICE_URL is not configured")
    url = base.rstrip("/") + "/api/v1/users"
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if q:
        params["q"] = q
    r = await ctx.http.get(url, headers=_headers(ctx), params=params)
    r.raise_for_status()
    return page_items(r.json())


async def fetch_listings_page(
    ctx: GraphQLContext,
    *,
    limit: int = 50,
    offset: int = 0,
    public_only: bool = False,
) -> dict[str, Any]:
    base = ctx.settings.marketplace_service_url
    if not base:
        raise RuntimeError(
            "MARKETPLACE_SERVICE_URL / CPEDGE_MARKETPLACE_SERVICE_URL is not configured"
        )
    url = base.rstrip("/") + "/api/v1/marketplace/listings"
    r = await ctx.http.get(
        url,
        headers=_headers(ctx),
        params={"limit": limit, "offset": offset, "public_only": public_only},
    )
    r.raise_for_status()
    return r.json()


async def fetch_acl_policies_json(ctx: GraphQLContext) -> list[dict[str, Any]]:
    base = ctx.settings.acl_service_url
    if not base:
        raise RuntimeError("ACL_SERVICE_URL / CPEDGE_ACL_SERVICE_URL is not configured")
    url = base.rstrip("/") + "/api/v1/acl/policies"
    r = await ctx.http.get(url, headers=_headers(ctx))
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


async def enforce_listing_read(ctx: GraphQLContext, listing_id: uuid.UUID) -> bool:
    """POST /acl/enforce for RBAC read on a concrete listing object."""
    base = ctx.settings.acl_service_url
    if not base:
        return True
    sub = ctx.user_sub
    if not sub:
        return False
    url = base.rstrip("/") + "/api/v1/acl/enforce"
    payload = {
        "model": "rbac",
        "sub": f"user:{sub}",
        "obj": f"/marketplace/listings/{listing_id}",
        "act": "read",
    }
    r = await ctx.http.post(url, headers=_headers(ctx), json=payload)
    r.raise_for_status()
    data = r.json()
    return bool(data.get("allow"))


async def fetch_ai_usage_history(
    ctx: GraphQLContext,
    *,
    limit: int = 50,
    offset: int = 0,
    user_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """GET ai-service ``/api/v1/ai/usage/history`` (``InferenceHistoryPage``)."""
    base = ctx.settings.ai_service_url
    if not base:
        raise RuntimeError("AI_SERVICE_URL / CPEDGE_AI_SERVICE_URL is not configured")
    url = base.rstrip("/") + "/api/v1/ai/usage/history"
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if user_id is not None:
        params["user_id"] = str(user_id)
    r = await ctx.http.get(url, headers=_headers(ctx), params=params)
    r.raise_for_status()
    return page_items(r.json())


async def post_inference(
    ctx: GraphQLContext,
    body: dict[str, Any],
) -> dict[str, Any]:
    base = ctx.settings.ai_service_url
    if not base:
        raise RuntimeError("AI_SERVICE_URL / CPEDGE_AI_SERVICE_URL is not configured")
    url = base.rstrip("/") + "/api/v1/ai/inference"
    r = await ctx.http.post(url, headers=_headers(ctx), json=body)
    r.raise_for_status()
    return r.json()
