"""Stateless edge entrypoint. Service owners own persistence and migrations."""
import os
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI
from controlplane_api.health import router as health_router
from controlplane_api.metrics import install_http_metrics
from controlplane_api.version import router as version_router
from controlplane_edge.aggregation import register_aggregation_routes
from controlplane_edge.graphql.register import register_graphql_routes
from controlplane_edge.grpc_server import grpc_server_lifespan
from controlplane_edge.register_cross_cutting import register_gateway_cross_cutting
from controlplane_edge.middleware.api_events import AccessEventPublisher


@asynccontextmanager
async def lifespan(app: FastAPI):
    from controlplane_api.config import settings as credential_settings
    credential_settings.require_edge_secrets()
    settings = app.state.edge_settings
    async with AccessEventPublisher(settings) as publisher:
        app.state.access_event_publisher = publisher
        async with grpc_server_lifespan(host=settings.grpc_host, port=settings.grpc_port,
                                        enabled=settings.grpc_enabled):
            async with httpx.AsyncClient(timeout=30.0) as client:
                app.state.graphql_http = client
                yield


def create_app() -> FastAPI:
    if os.environ.get("METRICS_OUTBOX_PROBE") == "1":
        raise ValueError("Edge has no local outbox; configure database probes on the events owner")
    app = FastAPI(title="Controlplane edge", version="0.2.0", lifespan=lifespan)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(version_router)
    register_aggregation_routes(app)
    register_graphql_routes(app)
    register_gateway_cross_cutting(app)
    install_http_metrics(app, service="controlplane-edge")
    return app


def main() -> None:
    from controlplane_api.metrics import start_metrics_server
    app = create_app()
    start_metrics_server()
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
