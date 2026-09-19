"""Gateway cross-cutting settings (CORS, rate limits, gRPC, OTEL)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewayCrossCuttingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cors_origins: str = Field(
        default="",
        description="Comma-separated origins; empty = allow * for dev only",
        validation_alias="CPEDGE_CORS_ORIGINS",
    )
    gateway_rate_limit_per_minute: int = Field(
        default=600,
        ge=1,
        validation_alias="CPEDGE_RATE_LIMIT_PER_MINUTE",
    )
    grpc_enabled: bool = Field(default=False, validation_alias="CPEDGE_GRPC_ENABLED")
    grpc_host: str = Field(default="127.0.0.1", validation_alias="CPEDGE_GRPC_HOST")
    grpc_port: int = Field(default=50051, ge=1, le=65535, validation_alias="CPEDGE_GRPC_PORT")
    graphql_dev_jwt_fallback: bool = Field(
        default=False,
        description="If true and Keycloak unset, decode Bearer without verify (dev only)",
        validation_alias="CPEDGE_GRAPHQL_DEV_JWT_FALLBACK",
    )
    otel_enabled: bool = Field(
        default=False,
        description="Set OTEL_EXPORTER_OTLP_ENDPOINT in env; this mirrors explicit enable",
        validation_alias="CPEDGE_OTEL_ENABLED",
    )
    api_access_events_enabled: bool = Field(
        default=False,
        description="Publish lightweight envelope after 2xx on /api/v1, /graphql",
        validation_alias="CPEDGE_API_ACCESS_EVENTS",
    )
    api_keys_service_url: str | None = Field(
        default=None,
        description="Base URL for api-keys-service (internal validate); unset disables X-Api-Key auth",
        validation_alias="CPEDGE_API_KEYS_SERVICE_URL",
    )
    api_key_rate_limit_per_minute: int = Field(
        default=60,
        ge=1,
        description="Per-IP sliding window for failed API key validation attempts",
        validation_alias="CPEDGE_API_KEY_FAIL_RATE_PER_MINUTE",
    )
    edge_proxy_enabled: bool = Field(
        default=True,
        description="Reverse-proxy extracted-service prefixes (users, auth, acl, …)",
        validation_alias="CPEDGE_EDGE_PROXY",
    )
    proxy_timeout_s: float = Field(
        default=30.0,
        gt=0,
        description="HTTP timeout for edge proxy upstreams",
        validation_alias="CPEDGE_PROXY_TIMEOUT_S",
    )


def parse_cors_origins(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]
