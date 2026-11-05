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

Main validation retains its exact qualified files in Actions artifacts. It does
not create GitHub releases or tags. Historical `test-<commit>` prereleases remain
qualification evidence and do not establish an accepted stable release.

Stable publication requires an explicit `vMAJOR.MINOR.PATCH` tag, the exact
successful main validation artifact, compatible declared contracts and an actual
immutable stable baseline. The publisher independently verifies that evidence;
successful caller jobs alone cannot establish acceptance. Missing evidence and
first-stable bootstrap remain closed. Package qualification, coordinated consumer
acceptance and runtime deployment remain separate.

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

### Actions qualification and stable publication

Main merges and workflow completion do not publish GitHub test releases. Exact
qualification files remain in Actions artifacts with finite retention. The pinned
publisher independently verifies a real immutable stable baseline and refuses
qualification snapshots, even if a caller job reports success. Existing valid
stable records are retained; no release, version change, deployment or human
approval prerequisite is introduced by this correction.

Version 0.2 rejects the retired tenant-claim URI, even alongside a current claim.
Reconfigure external issuers and require fresh tokens before upgrading; no legacy
tenant alias is accepted. Current tenant aliases must still agree.


### Initial stable declaration

When there is no accepted stable release, the pinned admission workflow checks
this repository's complete live release inventory and the exact owning package
versions against `releases/candidate`. A stable release or incomplete inventory
rejects this path. Candidate metadata identifies built artifacts; it does not
establish an accepted baseline or publish anything. The exact-pinned publisher
independently validates tested bytes and serializes any later explicit first
stable publication. Test snapshots remain qualification evidence only.

## Installed closure owner integration

The direct and transitive owner pins now match user-service integration #37.
The development consumer installs that exact reviewed user-service revision,
including its optional default-off verification erasure owner. Its fixture is
built from a clean Git archive and checked against the frozen complete graph.
The initial 302-case run passed in every context; after preserving the newly
merged onboarding route, all 303 cases pass in source, external wheel and
rebuilt-sdist contexts with no skips. The four installed-service cases send self/operator request, status and
hold traffic through the production edge proxy; original bearer authority,
query/body forwarding and tenant spoof refusal remain enforced. Private paths
and failed-retirement fallback remain denied. The edge package version and provider behavior are
preserved; this adoption publishes no release and activates no private runtime.

## Verification service

`CPEDGE_VERIFICATION_SERVICE_URL` optionally registers `/api/v1/verification`
and includes the service's OpenAPI/version discovery. Existing authentication and
tenant middleware still apply. The original browser credential is forwarded in
`X-Auth-Session-Token`; verification independently checks both credentials. Internal
erasure is not routed. Configure verification's exact trusted proxy CIDRs to
recover client IP from the edge-appended chain.

## License and transfer reconciliation

The owner package is Apache-2.0; source archives and wheels retain the exact
[license](LICENSE). PRs run the full installed-owner suite using verified,
immutable dependency wheel fixtures, without dependency credentials. Main checks
continue to validate the actual pinned Git graph. Private CI uses debrunners.

Panopticon's old account-closure-request URLs are superseded by the current native
closure routes. `tests/test_closure_auth.py` covers original-authority forwarding,
installed user-service consumption, tenant-header removal and rejection of old
or unsupported routes; the legacy URL test must not reintroduce those endpoints.
The age-confirmation tests belong to controlplane-identity and were transferred
there in PR #21. This edge's older immutable dependency graph still needs a
coordinated, fully qualified adoption of that fix. SDK generation, monolith version
routing and VM environment examples remain with their SDK/application/infra owners.
These source reconciliations do not establish deployment or anonymous installation.
