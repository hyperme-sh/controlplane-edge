"""Environment-driven base URLs for HTTP OpenAPI aggregation (docker-compose vs local)."""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenAPIAggregationSettings(BaseSettings):
    """Optional upstreams; unset = skip that service in the merged document."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    verification_service_url: str | None = Field(default=None, validation_alias="CPEDGE_VERIFICATION_SERVICE_URL")

    auth_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CPEDGE_AUTH_SERVICE_URL", "AUTH_SERVICE_URL"),
    )
    user_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CPEDGE_USER_SERVICE_URL", "USER_SERVICE_URL"),
    )
    payment_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CPEDGE_PAYMENT_SERVICE_URL", "PAYMENT_SERVICE_URL"),
    )
    acl_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CPEDGE_ACL_SERVICE_URL", "ACL_SERVICE_URL"),
    )
    marketplace_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CPEDGE_MARKETPLACE_SERVICE_URL",
            "MARKETPLACE_SERVICE_URL",
        ),
    )
    ai_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CPEDGE_AI_SERVICE_URL", "AI_SERVICE_URL"),
    )
    api_keys_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CPEDGE_API_KEYS_SERVICE_URL",
            "API_KEYS_SERVICE_URL",
        ),
    )
    template_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CPEDGE_TEMPLATE_SERVICE_URL",
            "TEMPLATE_SERVICE_URL",
        ),
    )
    tennessee_windage_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CPEDGE_TENNESSEE_WINDAGE_SERVICE_URL",
            "TENNESSEE_WINDAGE_SERVICE_URL",
        ),
    )
    hypermesh_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CPEDGE_HYPERMESH_SERVICE_URL",
            "HYPERMESH_SERVICE_URL",
        ),
    )
    hypermesh_gateway_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CPEDGE_HYPERMESH_GATEWAY_SERVICE_URL",
            "HYPERMESH_GATEWAY_SERVICE_URL",
        ),
    )
    aiuditor_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CPEDGE_AIUDITOR_SERVICE_URL",
            "AIUDITOR_SERVICE_URL",
        ),
    )
    turn_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CPEDGE_TURN_SERVICE_URL",
            "TURN_SERVICE_URL",
        ),
    )
    oracles_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CPEDGE_ORACLES_SERVICE_URL",
            "ORACLES_SERVICE_URL",
        ),
    )
    payments_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CPEDGE_PAYMENTS_SERVICE_URL",
            "PAYMENTS_SERVICE_URL",
        ),
    )

    openapi_fetch_timeout_s: float = Field(default=5.0, validation_alias="CPEDGE_OPENAPI_FETCH_TIMEOUT_S")

    def iter_remote_services(self) -> list[tuple[str, str | None]]:
        """(service_id, base_url) for each microservice."""
        return [
            ("verification", self.verification_service_url),
            ("auth", self.auth_service_url),
            ("user", self.user_service_url),
            ("payment", self.payment_service_url),
            ("acl", self.acl_service_url),
            ("marketplace", self.marketplace_service_url),
            ("ai", self.ai_service_url),
            ("api_keys", self.api_keys_service_url),
            ("template", self.template_service_url),
            ("tennessee_windage", self.tennessee_windage_service_url),
            ("hypermesh", self.hypermesh_service_url),
            ("hypermesh_gateway", self.hypermesh_gateway_service_url),
            ("aiuditor", self.aiuditor_service_url),
            ("turn", self.turn_service_url),
            ("oracles", self.oracles_service_url),
            ("payments", self.payments_service_url),
        ]
