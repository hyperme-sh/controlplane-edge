# Controlplane edge

FastAPI edge proxy, OpenAPI aggregation, GraphQL and optional ContractEcho gRPC.
Package `controlplane-edge` 0.1.0. The legacy `python -m controlplane_edge.main`
launcher still delegates to the shared `api.app`; an independent application
composition and container require separate qualification before deployment.
Runtime routing data is bundled as `controlplane_edge/product_routes.json`.
Generated gRPC modules come from the pinned `controlplane-proto` package.

The edge enforces authentication and tenant binding before forwarding protected
requests. Public paths are explicitly enumerated. Service destinations and optional
features use `CPEDGE_*` configuration; deployment-specific upstream registration
and credentials must be validated separately.

## Development

Use Python 3.13 and uv 0.11.26 with read access to the nine private repositories
named in `.github/workflows/package.yml`.

    uv sync --frozen
    bash scripts/check-package.sh

Tests run from source, a fresh normally installed wheel outside this checkout,
and a rebuilt source distribution. Wheel runtime/resource bytes must match source.
HTTP upstreams are mocked; gRPC checks use local test servers. These checks do
not establish live upstream, standalone container or deployment acceptance.
SDK generation and deployment-environment fixture contracts belong to separate
integration validation and are not part of this package's test result.

The main-only hosted workflow uses pinned actions, read-only contents and exact
repository credential headers. Actions remains disabled pending scoped
`DEPENDENCY_READ_TOKEN` access and hosted-worker policy.
