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

Use Python 3.13 and uv 0.11.26 with read access to the ten private repositories
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
repository credential headers. Private dependency access uses the repository-scoped `DEPENDENCY_READ_TOKEN`.

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
enabled. See the [shared release contract](https://github.com/hyperme-sh/.github/blob/7749591fccd30d46ba9b0adabe82114001c9d0de/actions/release-channel/README.md).

## One upstream credential authority

Protected requests must choose either `Authorization` or `X-Api-Key`. Supplying
both is rejected before either credential is validated, including blank or
malformed values. CORS preflight retains its existing handling. Once an API key
is validated and exchanged, the proxy sends only the signed bearer and the
validated tenant header; it removes the original API key. This adopts the edge
portion of Panopticon #702 without changing tenant claim compatibility or
upstream credential verification. Gateway-side attribution and private closure
routes remain separate owner adoption work.

## Account closure consumers

The edge adopts the same immutable identity/tenancy/core/database graph as the
installed user-service. Native closure identity is admitted only for the exact
self/operator action methods and paths; original bearer authority is forwarded
without caller-supplied tenant or actor claims. Internal lifecycle endpoints are
not public gateway routes, including OPTIONS. With retirement enforcement on,
failed validation cannot fall back to unverified development claims.

The package suite exercises the installed user-service forwarding router as a
consumer. Upstream authority replies are owned test fixtures; this does not
establish deployed provider, private TLS delivery or closure activation.

The active 305-case suite includes the combined REST, GraphQL and local gRPC
smoke case transferred from Panopticon d6d9541b72db2eb3f86cb8aedc071794eba116e3.
CI retains JUnit evidence and requires identical nonempty source, wheel and
sdist inventories with no skipped cases. Fixture registration identifiers are
stable so parametrized case identities can be compared exactly.

### Package preparation

`bash scripts/check-package.sh --fixtures` runs the existing source, fresh-wheel
and rebuilt-source-archive consumers without private Git credentials. Fixtures
are built from the exact clean Git revisions already pinned by this package;
the manifest records their digests and source provenance. The verifier checks
root metadata, the complete active lock graph and transitive wheel metadata.
Explicit private extras and unrecognized conditional pins fail closed.

The read-only pull-request workflow retains tested wheels, source archives and
an artifact-derived runtime inventory as Actions artifacts. It does not publish
releases. These are preparation evidence, not an accepted synchronized dependency
baseline: package version alignment, dependency adoption and comparison against
a qualified prior baseline remain separate work. Existing owner test boundaries
and live/provider qualification requirements continue to apply.

## Test qualification and stable acceptance

GitHub `test-<commit>` prereleases are development snapshots. Their embedded
package version does not reserve a stable version. Artifact and consumer evidence
belongs under `releases/qualification`. Owning-package and artifact validation
remain separate from stable release admission. Future test receipts must carry
an explicit non-stable classification.

`releases/accepted` and `SPANOPTICON_RELEASE_BASELINE_SHA` are reserved for an
actual immutable stable GitHub release. The pinned shared guard verifies the live
release channel, stable tag source and asset digests; a test snapshot cannot
become accepted through a provenance label. No stable baseline is recorded until
that release exists. Stable publication remains closed without a valid baseline;
first stable bootstrap and coordinated release qualification remain separate.
No stable version, approval prerequisite or deployment is introduced here.
