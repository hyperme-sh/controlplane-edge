"""Fetch upstream OpenAPI JSON over HTTP and merge with the monolith spec."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
from controlplane_edge.openapi_merge import merge_openapi

logger = logging.getLogger(__name__)


async def build_merged_openapi_for_version(
    app: FastAPI,
    settings: OpenAPIAggregationSettings,
    *,
    version_label: str,
) -> dict[str, Any]:
    """Build merged OpenAPI: local monolith ``get_openapi`` plus each configured upstream ``/openapi.json``."""

    monolith = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version="3.1.0",
        description=app.description or "",
        routes=app.routes,
    )
    specs: list[tuple[str, dict[str, Any]]] = [("controlplane-edge", monolith)]
    errors: list[dict[str, str]] = []

    timeout = httpx.Timeout(settings.openapi_fetch_timeout_s)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for svc_id, base in settings.iter_remote_services():
            if not base:
                continue
            url = base.rstrip("/") + "/openapi.json"
            try:
                r = await client.get(url)
                r.raise_for_status()
                specs.append((svc_id, r.json()))
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenAPI fetch failed for %s (%s): %s", svc_id, url, exc)
                errors.append({"service": svc_id, "url": url, "detail": str(exc)})

    merged = merge_openapi(
        specs,
        title=f"(s)panopticon Aggregated API ({version_label})",
        version=f"{version_label}.0.0",
    )
    meta = merged.setdefault("x-controlplane-edge-meta", {})
    if errors:
        meta["fetch_errors"] = errors
    return merged
