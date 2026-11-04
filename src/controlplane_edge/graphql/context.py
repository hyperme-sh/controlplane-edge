"""Per-request GraphQL context: forwarded auth, tenant, shared httpx, DataLoaders."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
from strawberry.dataloader import DataLoader
from strawberry.fastapi import BaseContext

from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings


@dataclass
class GraphQLLoaders:
    """Batch ACL enforce for listing ids (avoids duplicate calls per id in one request)."""

    acl_listing_read: DataLoader[uuid.UUID, bool]


class GraphQLContext(BaseContext):
    """Custom Strawberry context (must subclass ``BaseContext`` for FastAPI integration)."""

    def __init__(
        self,
        *,
        authorization: str | None,
        tenant_id: uuid.UUID | None,
        user_sub: str | None,
        settings: OpenAPIAggregationSettings,
        http: httpx.AsyncClient,
        loaders: GraphQLLoaders | None = None,
    ) -> None:
        super().__init__()
        self.authorization = authorization
        self.tenant_id = tenant_id
        self.user_sub = user_sub
        self.settings = settings
        self.http = http
        self.loaders = loaders
