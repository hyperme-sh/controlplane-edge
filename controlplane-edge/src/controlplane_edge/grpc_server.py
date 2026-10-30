"""Minimal async gRPC server for ContractEcho (auth via metadata)."""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import grpc.aio
from grpc.aio import ServicerContext

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROTO_DIR = _REPO_ROOT / "proto" / "panopticon" / "v1"
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

import contractecho_pb2_grpc  # noqa: E402

from controlplane_edge.auth_utils import resolve_bearer_claims_sync  # noqa: E402


class ContractEchoServicer(contractecho_pb2_grpc.ContractEchoServicer):
    def EchoUser(self, request, context: ServicerContext):
        _require_auth_metadata(context)
        return request

    def EchoListing(self, request, context: ServicerContext):
        _require_auth_metadata(context)
        return request

    def EchoTokenUsage(self, request, context: ServicerContext):
        _require_auth_metadata(context)
        return request


def _require_auth_metadata(context: ServicerContext) -> None:
    meta = {k.lower(): v for k, v in context.invocation_metadata()}
    raw = meta.get("authorization")
    if not raw:
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "missing authorization metadata")
    token = raw
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    if token.startswith("Bearer "):
        token = token[7:].strip()
    claims = resolve_bearer_claims_sync(token)
    if not claims:
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid token")
    tid = meta.get("x-tenant-id")
    if isinstance(tid, bytes):
        tid = tid.decode("utf-8")
    if not tid:
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, "missing x-tenant-id metadata")


@asynccontextmanager
async def grpc_server_lifespan(
    *,
    host: str,
    port: int,
    enabled: bool,
) -> AsyncIterator[grpc.aio.Server | None]:
    if not enabled:
        yield None
        return

    server = grpc.aio.server()
    contractecho_pb2_grpc.add_ContractEchoServicer_to_server(ContractEchoServicer(), server)
    bound = server.add_insecure_port(f"{host}:{port}")
    listen = f"{host}:{bound}"
    setattr(server, "bound_port", bound)
    await server.start()
    logger.info("gRPC ContractEcho listening on %s", listen)
    try:
        yield server
    finally:
        await server.stop(grace=5)
        logger.info("gRPC server stopped")
