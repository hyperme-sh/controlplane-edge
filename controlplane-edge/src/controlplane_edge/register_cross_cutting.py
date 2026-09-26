"""CORS, auth, rate limit, API access events, optional OpenTelemetry for the gateway app."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from api.infrastructure.tenant_user_rate_limiter import TenantUserRateLimiter
from controlplane_edge.edge_proxy import register_edge_proxy
from controlplane_edge.edge_settings import GatewayCrossCuttingSettings, parse_cors_origins
from controlplane_edge.public_hypermesh_browse import router as public_hypermesh_browse_router
from controlplane_edge.service_versions import router as service_versions_router
from controlplane_edge.middleware.api_events import GatewayApiAccessEventMiddleware
from controlplane_edge.middleware.api_key_bruteforce import ApiKeyFailureTracker
from controlplane_edge.middleware.policy import GatewayAuthMiddleware
from controlplane_edge.middleware.rate_limit import GatewayRateLimitMiddleware

logger = logging.getLogger(__name__)


def maybe_instrument_otel(app: FastAPI) -> None:
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") and not GatewayCrossCuttingSettings().otel_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except ImportError:
        logger.warning("OpenTelemetry packages not installed; skip instrumentation")
        return

    resource = Resource.create(
        {"service.name": os.environ.get("OTEL_SERVICE_NAME", "panopticon-gateway")}
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except ImportError:
        pass
    logger.info("OpenTelemetry FastAPI + httpx instrumentation enabled")


def register_gateway_cross_cutting(app: FastAPI) -> None:
    """Register middlewares (order: inner events → rate limit → auth → outer CORS)."""

    settings = GatewayCrossCuttingSettings()
    app.state.edge_settings = settings
    app.state.gateway_rate_limiter = TenantUserRateLimiter(
        per_minute=settings.gateway_rate_limit_per_minute
    )
    app.state.api_key_failure_tracker = ApiKeyFailureTracker(
        max_failures_per_minute=settings.api_key_rate_limit_per_minute
    )

    maybe_instrument_otel(app)

    # Live GET is proxied to hypermesh-service. These routes exist so
    # /openapi.json lists the public Hypermesh browse paths at their real URLs.
    app.include_router(public_hypermesh_browse_router)
    # Peer /version summary. Unauthenticated; see public_paths.
    app.include_router(service_versions_router)

    # Innermost: proxy matched prefixes after auth / rate-limit have run.
    register_edge_proxy(app)

    app.add_middleware(GatewayApiAccessEventMiddleware, settings=settings)
    app.add_middleware(GatewayRateLimitMiddleware)
    app.add_middleware(GatewayAuthMiddleware, settings=settings)

    origins = parse_cors_origins(settings.cors_origins)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    logger.info("Gateway cross-cutting middleware registered (auth, rate limit, CORS, optional events)")
