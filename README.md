# Controlplane edge

FastAPI edge proxy, OpenAPI aggregation, GraphQL and optional ContractEcho gRPC.
Package `controlplane-edge` 0.1.0. The legacy `python -m controlplane_edge.main`
launcher still delegates to the shared `api.app`; an independent application
composition and container require separate qualification before deployment.
Runtime routing data is bundled as `controlplane_edge/product_routes.json`.
Generated gRPC modules come from the pinned `controlplane-proto` package.

The edge enforces authentication and tenant binding before forwarding protected
requests. Public paths are explicitly enumerated. Proxy requests use only the
caller's cookies; the shared proxy client does not persist upstream cookies.
Opaque site-token forwarding is limited to explicit methods and paths owned by
upstreams that validate those credentials. It does not authenticate local routes
such as the protected service-version endpoint. Service destinations and optional
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

The main-only shared-runner workflow uses pinned actions, read-only contents and exact
repository credential headers. Actions remains disabled pending scoped
`DEPENDENCY_READ_TOKEN` access and shared-runner qualification.

## Public host release downloads

Anonymous GETs admit only published metadata and versioned Linux arm64/amd64 or
Darwin arm64 agent/installer names. Unsupported targets, private files and
mutation methods remain protected. Redirects preserve the no-store and
no-referrer headers. This is the edge portion of transitional Panopticon #726;
actual signed downloads and live deployment remain separate acceptance gates.

## Release channels

Successful main-push validation retains the validated Python wheel and source distribution and publishes
an immutable `test-<commit>` GitHub prerelease. Push a `vMAJOR.MINOR.PATCH`
tag at that tested commit to promote the exact files to a stable release,
without rebuilding. Repository visibility applies to all package assets.
Package metadata versions are preserved; these are GitHub distribution snapshots,
not automatic PyPI publication or service deployment.

Promotion requires the original Actions artifact (90-day requested retention;
organization policy may shorten it). Expired evidence fails closed: validate a
new main revision. The publisher verifies the run, source, workflow and artifact
digest independently of release metadata. Repository immutable releases must be
enabled. See the [shared release contract](https://github.com/hyperme-sh/.github/blob/3352fb1347e7920ec1d5cd14792ba3038a81abcb/actions/release-channel/README.md).
