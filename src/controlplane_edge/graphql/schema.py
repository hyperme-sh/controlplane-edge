"""Strawberry schema: tenantUsers, listings, aclPolicies, aiUsage, runInference."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import strawberry
from strawberry.exceptions import GraphQLError
from strawberry.experimental.pydantic import type as pydantic_type
from strawberry.scalars import JSON

from spanopticon_models import Listing, ListingType, PriceType, TokenUsage

from controlplane_edge.graphql import clients
from controlplane_edge.graphql.context import GraphQLContext


@strawberry.type
class ListingGQL:
    """Marketplace listing (mapped from REST JSON via ``_listing_from_api``)."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    seller_id: uuid.UUID
    title: str
    description: str
    listing_type: str
    price_type: str
    price_amount: int | None
    metadata: JSON


@strawberry.type
class TenantUser:
    id: strawberry.ID
    email: str
    first_name: str
    last_name: str
    is_active: bool


@strawberry.type
class CasbinPolicyRow:
    id: int
    ptype: str | None
    v0: str | None
    v1: str | None
    v2: str | None
    v3: str | None
    v4: str | None
    v5: str | None


@pydantic_type(model=TokenUsage, all_fields=True)
class TokenUsageGQL:
    pass


@strawberry.type
class InferenceResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: str
    inference_id: str


@strawberry.input
class RunInferenceInput:
    prompt: str
    model: str
    max_tokens: int | None = None
    billing_mode: str = "none"
    budget_id: uuid.UUID | None = None
    stripe_customer_id: str | None = None
    purchase_id: uuid.UUID | None = None
    license_key: str | None = None


def _require_auth(ctx: GraphQLContext) -> None:
    if not ctx.authorization or not ctx.authorization.startswith("Bearer "):
        raise GraphQLError("Unauthorized", extensions={"code": "UNAUTHENTICATED"})
    if ctx.tenant_id is None:
        raise GraphQLError("Missing X-Tenant-ID header", extensions={"code": "BAD_USER_INPUT"})


def _listing_from_api(row: dict[str, Any]) -> Listing:
    return Listing(
        id=uuid.UUID(str(row["id"])),
        tenant_id=uuid.UUID(str(row["tenant_id"])),
        seller_id=uuid.UUID(str(row["seller_id"])),
        title=row["title"],
        description=row.get("description") or "",
        type=ListingType(str(row["listing_type"])),
        price_type=PriceType(str(row["price_type"])),
        price_amount=row.get("price_amount"),
        metadata=row.get("metadata") or {},
    )


def _listing_gql_from_pydantic(l: Listing) -> ListingGQL:
    return ListingGQL(
        id=l.id,
        tenant_id=l.tenant_id,
        seller_id=l.seller_id,
        title=l.title,
        description=l.description,
        listing_type=l.type.value,
        price_type=l.price_type.value,
        price_amount=l.price_amount,
        metadata=l.metadata,
    )


def _aware_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _token_usage_gql(row: dict[str, Any], tenant_id: uuid.UUID) -> TokenUsageGQL:
    """Map ai-service ``InferenceRecordResponse`` onto shared ``TokenUsage``."""
    ts = _aware_timestamp(row.get("created_at") or row.get("timestamp"))
    kwargs: dict[str, Any] = {
        "user_id": uuid.UUID(str(row["user_id"])),
        "tenant_id": tenant_id,
        "model": str(row["model"]),
        "input_tokens": int(row["input_tokens"]),
        "output_tokens": int(row["output_tokens"]),
        "cost": row.get("cost_usd", row.get("cost", 0)),
    }
    if ts is not None:
        kwargs["timestamp"] = ts
    return TokenUsageGQL.from_pydantic(TokenUsage(**kwargs))


@strawberry.type
class Query:
    @strawberry.field(description="Users in the current tenant (user-service UserListPage)")
    async def tenant_users(
        self,
        info: strawberry.Info,
        limit: int = 50,
        offset: int = 0,
        q: str | None = None,
    ) -> list[TenantUser]:
        ctx: GraphQLContext = info.context
        _require_auth(ctx)
        raw = await clients.fetch_users_json(ctx, limit=limit, offset=offset, q=q)
        out: list[TenantUser] = []
        for row in raw:
            out.append(
                TenantUser(
                    id=strawberry.ID(str(row["id"])),
                    email=row["email"],
                    first_name=row.get("first_name") or "",
                    last_name=row.get("last_name") or "",
                    is_active=bool(row.get("is_active", True)),
                )
            )
        return out

    @strawberry.field(description="Marketplace listings (optional ACL filter uses DataLoader)")
    async def listings(
        self,
        info: strawberry.Info,
        apply_acl_filter: bool = False,
        limit: int = 50,
        offset: int = 0,
        public_only: bool = False,
    ) -> list[ListingGQL]:
        ctx: GraphQLContext = info.context
        _require_auth(ctx)
        data = await clients.fetch_listings_page(
            ctx, limit=limit, offset=offset, public_only=public_only
        )
        items_raw = data.get("items") if isinstance(data, dict) else []
        listings = [_listing_from_api(x) for x in items_raw]
        if not apply_acl_filter:
            return [_listing_gql_from_pydantic(x) for x in listings]
        if ctx.loaders is None:
            return [_listing_gql_from_pydantic(x) for x in listings]
        out: list[ListingGQL] = []
        for it in listings:
            ok = await ctx.loaders.acl_listing_read.load(it.id)
            if ok:
                out.append(_listing_gql_from_pydantic(it))
        return out

    @strawberry.field(description="Casbin policy rows (acl-service)")
    async def acl_policies(self, info: strawberry.Info) -> list[CasbinPolicyRow]:
        ctx: GraphQLContext = info.context
        _require_auth(ctx)
        raw = await clients.fetch_acl_policies_json(ctx)
        return [
            CasbinPolicyRow(
                id=int(r["id"]),
                ptype=r.get("ptype"),
                v0=r.get("v0"),
                v1=r.get("v1"),
                v2=r.get("v2"),
                v3=r.get("v3"),
                v4=r.get("v4"),
                v5=r.get("v5"),
            )
            for r in raw
        ]

    @strawberry.field(
        description="AI usage records from ai-service GET /api/v1/ai/usage/history"
    )
    async def ai_usage(
        self,
        info: strawberry.Info,
        limit: int = 50,
        offset: int = 0,
        user_id: uuid.UUID | None = None,
    ) -> list[TokenUsageGQL]:
        ctx: GraphQLContext = info.context
        _require_auth(ctx)
        raw = await clients.fetch_ai_usage_history(
            ctx, limit=limit, offset=offset, user_id=user_id
        )
        assert ctx.tenant_id is not None
        return [_token_usage_gql(row, ctx.tenant_id) for row in raw]


@strawberry.type
class Mutation:
    @strawberry.mutation(description="Metered inference via ai-service (budget / entitlement server-side)")
    async def run_inference(self, info: strawberry.Info, input: RunInferenceInput) -> InferenceResult:
        ctx: GraphQLContext = info.context
        _require_auth(ctx)
        body: dict[str, Any] = {
            "prompt": input.prompt,
            "model": input.model,
            "billing_mode": input.billing_mode,
        }
        if input.max_tokens is not None:
            body["max_tokens"] = input.max_tokens
        if input.budget_id is not None:
            body["budget_id"] = str(input.budget_id)
        if input.stripe_customer_id is not None:
            body["stripe_customer_id"] = input.stripe_customer_id
        if input.purchase_id is not None:
            body["purchase_id"] = str(input.purchase_id)
        if input.license_key is not None:
            body["license_key"] = input.license_key
        data = await clients.post_inference(ctx, body)
        cost = data.get("cost_usd", 0)
        if isinstance(cost, (int, float)):
            cost_s = str(Decimal(str(cost)))
        else:
            cost_s = str(cost)
        return InferenceResult(
            text=data["text"],
            model=data["model"],
            input_tokens=int(data["input_tokens"]),
            output_tokens=int(data["output_tokens"]),
            cost_usd=cost_s,
            inference_id=str(data["inference_id"]),
        )


schema = strawberry.Schema(query=Query, mutation=Mutation)
