"""Documented public Hypermesh browse paths (GET catalog, classes, and nodes).

These paths already exist on hypermesh-service. The gateway lists them on
``/openapi.json`` so the marketing site and renters can find them without
digging through ``/_upstream/hypermesh/…``. The edge proxy still forwards
the live GET to hypermesh-service.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

# Exact paths only. Do not prefix-match /api/v1/hypermesh.
PUBLIC_HYPERMESH_BROWSE_PATHS = frozenset(
    {
        "/api/v1/hypermesh/catalog",
        "/api/v1/hypermesh/classes",
        "/api/v1/hypermesh/nodes",
        "/api/v1/hypermesh/ready",
        "/api/v1/hypermesh/pricing/transparency",
    }
)

router = APIRouter(prefix="/api/v1/hypermesh", tags=["hypermesh"])


def is_public_hypermesh_browse(path: str, method: str = "GET") -> bool:
    """True only for exact public browse GET paths, including pricing metadata."""

    if method.upper() != "GET":
        return False
    norm = path.rstrip("/") or "/"
    return norm in PUBLIC_HYPERMESH_BROWSE_PATHS


@router.get(
    "/catalog",
    summary="List public Hypermesh catalog",
    description=(
        "Public Hypermesh / Hyperme.sh Full Model catalog. No key. Returns "
        "marketplace rows whose hardware class has public_sku=true. No private "
        "SKUs, host credentials, or tickets. Checkout, lease, and chat stay "
        "authenticated. Served by hypermesh-service via the gateway edge proxy."
    ),
    operation_id="listPublicHypermeshCatalog",
    openapi_extra={"security": []},
    responses={
        200: {
            "description": "Public Hypermesh catalog entries (public_sku=true classes only)",
        }
    },
)
async def list_public_hypermesh_catalog() -> list[dict]:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Hypermesh catalog is served by hypermesh-service",
    )


@router.get(
    "/classes",
    summary="List public Hypermesh classes",
    description=(
        "Public Hypermesh / Hyperme.sh hardware classes. No key. Returns the "
        "marketplace list with public_sku=true only. Thor is not listed. "
        "Tennessee Windage is a different product and is not on this path. "
        "Checkout, lease, and chat stay authenticated. Served by "
        "hypermesh-service via the gateway edge proxy."
    ),
    operation_id="listPublicHypermeshClasses",
    openapi_extra={"security": []},
    responses={
        200: {
            "description": "Public Hypermesh hardware classes (public_sku=true only)",
        }
    },
)
async def list_public_hypermesh_classes() -> list[dict]:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Hypermesh classes are served by hypermesh-service",
    )


@router.get(
    "/nodes",
    summary="List public Hypermesh nodes",
    description=(
        "Public Hypermesh / Hyperme.sh boxes. No key. Returns public_sku "
        "classes only. Public label is class plus a short id. No serial, "
        "org, keys, or device id. Checkout, lease, and chat stay "
        "authenticated. Served by hypermesh-service via the gateway edge proxy."
    ),
    operation_id="listPublicHypermeshNodes",
    openapi_extra={"security": []},
    responses={
        200: {
            "description": "Public Hypermesh nodes (public_sku=true classes only)",
        }
    },
)
async def list_public_hypermesh_nodes() -> list[dict]:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Hypermesh nodes are served by hypermesh-service",
    )


@router.get(
    "/ready",
    summary="Hypermesh process is listening",
    description=(
        "Cheap liveness for the deployed hypermesh image. No key. The live "
        "response carries x-hypermesh-revision. Served by hypermesh-service "
        "via the gateway edge proxy."
    ),
    operation_id="getPublicHypermeshReady",
    openapi_extra={"security": []},
    responses={200: {"description": "Hypermesh process is listening"}},
)
async def get_public_hypermesh_ready() -> dict:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Hypermesh ready is served by hypermesh-service",
    )


@router.get(
    "/pricing/transparency",
    summary="Read public Hypermesh pricing rules and pool flags",
    description=(
        "No key required. Marketplace public_sku pools only. Returns the active "
        "ruleset version and public_summary, plus latest realtime pool flags. "
        "Null flags mean no completed round. Served by hypermesh-service."
    ),
    operation_id="getPublicHypermeshPricingTransparency",
    openapi_extra={"security": []},
    responses={200: {"description": "Public ruleset and pool flags"},
               503: {"description": "Pricing transparency unavailable"}},
)
async def get_public_hypermesh_pricing_transparency() -> dict:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Hypermesh pricing transparency is served by hypermesh-service",
    )
