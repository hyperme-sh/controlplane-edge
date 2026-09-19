"""Register HTTP-aggregated OpenAPI routes on the controlplane FastAPI app."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Query
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
from controlplane_edge.openapi_aggregate import build_merged_openapi_for_version
from controlplane_edge.openapi_merge import diff_openapi_changelog, diff_openapi_to_markdown

logger = logging.getLogger(__name__)


def register_aggregation_routes(app: FastAPI) -> None:
    """Mount ``/v1|v2/openapi.json``, Swagger UI, and ``/changelog/openapi``."""

    settings = OpenAPIAggregationSettings()

    @app.get("/v1/openapi.json", include_in_schema=False)
    async def v1_openapi_json() -> JSONResponse:
        merged = await build_merged_openapi_for_version(app, settings, version_label="v1")
        return JSONResponse(merged)

    @app.get("/v1/docs", include_in_schema=False)
    async def v1_docs() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url="/v1/openapi.json",
            title=f"{app.title} — aggregated v1",
        )

    @app.get("/v2/openapi.json", include_in_schema=False)
    async def v2_openapi_json() -> JSONResponse:
        merged = await build_merged_openapi_for_version(app, settings, version_label="v2")
        return JSONResponse(merged)

    @app.get("/v2/docs", include_in_schema=False)
    async def v2_docs() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url="/v2/openapi.json",
            title=f"{app.title} — aggregated v2",
        )

    @app.get("/changelog/openapi", include_in_schema=False)
    async def changelog_openapi(
        from_ver: str = Query("v1", alias="from"),
        to_ver: str = Query("v2", alias="to"),
    ) -> dict:
        a = await build_merged_openapi_for_version(app, settings, version_label=from_ver)
        b = await build_merged_openapi_for_version(app, settings, version_label=to_ver)
        return diff_openapi_changelog(a, b)

    @app.get("/changelog/openapi.md", include_in_schema=False)
    async def changelog_openapi_md(
        from_ver: str = Query("v1", alias="from"),
        to_ver: str = Query("v2", alias="to"),
    ) -> PlainTextResponse:
        a = await build_merged_openapi_for_version(app, settings, version_label=from_ver)
        b = await build_merged_openapi_for_version(app, settings, version_label=to_ver)
        diff = diff_openapi_changelog(a, b)
        md = diff_openapi_to_markdown(
            diff,
            title=f"OpenAPI changelog ({from_ver} → {to_ver})",
        )
        return PlainTextResponse(md, media_type="text/markdown; charset=utf-8")

    logger.info("Gateway OpenAPI aggregation routes registered (/v1/docs, /changelog/openapi)")
