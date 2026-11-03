"""DataLoaders for batched ACL checks (listing read)."""

from __future__ import annotations

import uuid

from strawberry.dataloader import DataLoader

from controlplane_edge.graphql import clients
from controlplane_edge.graphql.context import GraphQLContext, GraphQLLoaders


def build_loaders(ctx: GraphQLContext) -> GraphQLLoaders:
    async def load_acl_listing_read(keys: list[uuid.UUID]) -> list[bool]:
        return [await clients.enforce_listing_read(ctx, k) for k in keys]

    return GraphQLLoaders(
        acl_listing_read=DataLoader(load_fn=load_acl_listing_read),
    )
