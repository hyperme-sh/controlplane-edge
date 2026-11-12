# Controlplane edge

`controlplane-edge` 0.2.0 is the HTTP edge for the Hypermesh control plane. It authenticates callers, binds each request to a tenant, and reverse-proxies existing service prefixes. It also publishes one aggregated OpenAPI document, a GraphQL API, and an optional ContractEcho gRPC service. Generated gRPC modules come from the pinned `controlplane-proto` package. Product prefix declarations live in `src/controlplane_edge/product_routes.json`.

## Why

Hypermesh clients need one front door for the control plane: account and tenancy APIs, marketplace and payment calls, host-agent traffic, and public catalog reads. Each of those services keeps its own process and its own OpenAPI document. This package is the gateway that checks credentials once, forwards the call to the service that owns the path, and presents the combined HTTP surface to browsers, host agents, and integrators.

## How it works

`python -m controlplane_edge.main` listens on `HOST` and `PORT` (default `0.0.0.0:8000`) using edge's own FastAPI application. Startup opens no database, seeds no roles, and runs no migrations. Identity helpers come from the neutral identity package. Business operations use the configured owner HTTP APIs. The legacy application's unowned routes (including local roles, tenants and dashboard handlers) are no longer mounted; authenticated requests to an unowned path return 404. Tenant identity is bound to verified credentials, not looked up in a local database from the hostname.

Request handling:

1. Public paths are an explicit allowlist (health, docs, OpenAPI, login and refresh, the Stripe webhook, selected Hypermesh browse and host-agent routes, and `GET /graphql`). Everything else requires a credential.
2. Send either `Authorization: Bearer` or `X-Api-Key`. A request that carries both is rejected before either value is checked.
3. An API key is validated at `CPEDGE_API_KEYS_SERVICE_URL`, exchanged for a short-lived signed bearer, and removed. Upstream calls receive that bearer and the tenant id taken from the validated credential. `X-Tenant-ID` must match the tenant in the token. The current tenant claim is `https://spanopticon.dev/tenant_id`. When `tenant_id` is also present, the two values must be the same UUID.
4. Account-closure calls are limited to `POST /api/v1/me/account-closure`, `GET` and `POST /api/v1/operator/account-closures`, and `POST /api/v1/operator/account-closures/hold`. Those routes forward the original bearer and do not accept a caller-supplied tenant or actor claim. Paths under `/api/v1/internal/` are not gateway routes.
5. `/api/v1/operator/*` forwards to user-service, which enforces console/support authority and reads durable bans and audit records. The account-closure routes above retain their separate credential handling. A matched prefix is streamed to the configured upstream. The proxy forwards the caller’s cookies, preserves separate upstream `Set-Cookie` fields and does not store upstream cookies. Hop-by-hop headers are dropped. Opaque `hm_site_` tokens are forwarded only for the site-job, auditor-ticket, and grant methods that the upstream validates.
6. Card-checkout paths answer `410`. Lease payment is `POST /api/v1/payments/usdc/lease-payments` on payment-service.
7. Configured upstreams contribute their `/openapi.json` to `GET /v1/openapi.json` and `GET /v2/openapi.json` (Swagger UI at `/v1/docs` and `/v2/docs`). `GET /changelog/openapi` and `GET /changelog/openapi.md` diff those documents.
8. `POST /graphql` serves tenant users, marketplace listings, ACL policy rows, and AI token usage, plus the `runInference` mutation. Those fields forward the policy-selected bearer, including an exchanged API-key credential, to the user, marketplace, ACL, and AI services. `GET /graphql` is the playground.
9. With `CPEDGE_GRPC_ENABLED=true`, ContractEcho answers `EchoUser`, `EchoListing`, and `EchoTokenUsage` on `CPEDGE_GRPC_HOST`:`CPEDGE_GRPC_PORT` (default `127.0.0.1:50051`). Callers pass `authorization` and `x-tenant-id` metadata.

`CPEDGE_VERIFICATION_SERVICE_URL` adds the `/api/v1/verification` prefix to the proxy and to OpenAPI discovery. The exact POST routes under `/api/v1/verification/webhooks/sumsub/sandbox/` for `applicant-deleted` and `review-events` forward the raw body and signature headers under the anonymous rate limit. Verification authenticates the sandbox delivery. Internal erasure URLs are not routed. `EDGE_VERSIONS_ACCESS` controls `GET /versions`: `authenticated` (the default), `public`, or `off` (`404`, and upstream version probes are skipped). Set `off` on a production edge.

## Practical use

Install Python 3.13 and [uv](https://docs.astral.sh/uv/) 0.11.26. Runtime and development dependencies are public git pins under `github.com/hyperme-sh`; `uv sync --frozen` does not need a private credential.

```sh
git clone https://github.com/hyperme-sh/controlplane-edge.git
cd controlplane-edge
uv python install 3.13
uv sync --frozen
```

Point each `CPEDGE_*_SERVICE_URL` at its service owner. Unset services are omitted from the merged OpenAPI document; a proxied path whose URL is unset answers `503`. Edge needs no PostgreSQL or Redis setup. Owner services manage their own schema and startup.

```sh
export KEYCLOAK_JWKS_URL=https://id.example/realms/controlplane/protocol/openid-connect/certs
export KEYCLOAK_ISSUER=https://id.example/realms/controlplane
export API_KEY_EXCHANGE_JWT_SECRET='replace-with-a-private-value'
export API_KEYS_INTERNAL_TOKEN='replace-with-a-private-value'
export CPEDGE_AUTH_SERVICE_URL=http://127.0.0.1:8001
export CPEDGE_USER_SERVICE_URL=http://127.0.0.1:8002
export CPEDGE_API_KEYS_SERVICE_URL=http://127.0.0.1:8003
export CPEDGE_PAYMENT_SERVICE_URL=http://127.0.0.1:8004
export CPEDGE_ACL_SERVICE_URL=http://127.0.0.1:8005
export CPEDGE_MARKETPLACE_SERVICE_URL=http://127.0.0.1:8006
export CPEDGE_AI_SERVICE_URL=http://127.0.0.1:8007
export CPEDGE_HYPERMESH_SERVICE_URL=http://127.0.0.1:8010
export CPEDGE_CORS_ORIGINS=http://localhost:3000
export EDGE_VERSIONS_ACCESS=off
export HOST=127.0.0.1
export PORT=8000
uv run python -m controlplane_edge.main
```

Empty `API_KEY_EXCHANGE_JWT_SECRET` and `API_KEYS_INTERNAL_TOKEN` values, and the published development defaults, are rejected. API-key exchange stays disabled until both are private values and `CPEDGE_API_KEYS_SERVICE_URL` is set.

```sh
curl -sS "http://127.0.0.1:8000/api/v1/health"
curl -sS "http://127.0.0.1:8000/v1/openapi.json" | head
curl -sS "http://127.0.0.1:8000/api/v1/hypermesh/catalog"
```

The same `CPEDGE_` names accept an unprefixed alias for several services (`AUTH_SERVICE_URL`, `USER_SERVICE_URL`, `HYPERMESH_SERVICE_URL`, and the other aliases on `OpenAPIAggregationSettings`). Gateway defaults include `CPEDGE_RATE_LIMIT_PER_MINUTE=600`, `CPEDGE_PROXY_TIMEOUT_S=30`, and `CPEDGE_EDGE_PROXY=true`.

## How Hypermesh uses it

This process is the control-plane HTTP front for lease, host, and renter traffic. Renters send paid prompts to `hypermesh-gateway` on its own hostname. The aggregated OpenAPI document includes that service. The reverse proxy has no route to it, so a paid ticket keeps working while the control plane is down. The orchestrator is served on its own hostname as well.

| Caller | Traffic | Where it goes |
| --- | --- | --- |
| Public site and renters browsing | Anonymous `GET` of `/api/v1/hypermesh/catalog`, `/classes`, `/nodes`, `/ready`, `/pricing/transparency`, `/public/host-installation`, and `/public/host-releases/{test\|prod}` plus the published metadata and installer names | `hypermesh-service` (`CPEDGE_HYPERMESH_SERVICE_URL`) |
| Hosts | Exact enroll, heartbeat, onboarding, certification, identity bind and token, tunnel, scorecard, job, and update calls. The body carries a one-time enroll token, or the request carries the device bearer. | `hypermesh-service`. `POST /api/v1/aiuditor/machine/renew` goes to AIuditor. |
| Renters paying for a lease | `POST /api/v1/payments/usdc/lease-payments` with a bearer or API key and a tenant binding | payment-service |
| Portal and operators | Users, groups, organizations, account closure, marketplace, ACL, and `/api/v1/ai/inference`, `/complete`, and `/usage` | The service that owns that prefix |
| Site machines | Bearer values that start with `hm_site_` on the explicit site-job, auditor-ticket, and grant routes | `hypermesh-service` |

Anonymous host-release downloads admit the channel index and, under a published version directory, `release.json`, `platforms.json`, `checksums.txt` (and `.sig` / `.asc`), `bootstrap.py`, `hypermesh-release.pub`, and `hypermesh-agent` / `hypermesh-deploy` builds for `linux_arm64`, `linux_amd64`, and `darwin_arm64`. Other names and other methods stay on the authenticated path. Upstream `Cache-Control` and `Referrer-Policy` headers are passed through. `deploy/Dockerfile.host-downloads` is the image bridge that serves this public download surface.

Authenticated renter and operator calls use the same credential and tenant rules as the rest of the gateway. Lease creation and chat use those rules. Card checkout answers `410`. Public catalog, class, and node responses are the hypermesh-service lists of hardware classes with `public_sku=true`.

## Develop and test

From a checkout, with Python 3.13:

```sh
uv sync --frozen
bash scripts/check-package.sh
```

`scripts/check-package.sh` runs the suite from source, from a freshly installed wheel outside this checkout, and from a wheel rebuilt from the source distribution. Wheel bytes are checked against the source tree. HTTP upstreams are mocked. gRPC checks use a local server. These checks cover this package; they do not stand in for a live upstream or a deployment.

`bash scripts/check-package.sh --fixtures` repeats that run using the dependency wheels pinned by `tests_artifacts/dependencies/manifest.json`, still without private git credentials.

Pull requests run `.github/workflows/preparation.yml`. Pushes to `main` run `.github/workflows/package.yml`. Public repositories use GitHub-hosted Ubuntu 24.04. Private repositories use the self-hosted `debrunner` runners. Release mechanics are in [docs/releasing.md](docs/releasing.md). Compatibility rules for the shared line are in [docs/release-policy.md](docs/release-policy.md).

## Release and versioning

Package `controlplane-edge` is **0.2.0** on release line **0.2** (`release-policy.json`, `pyproject.toml`). Version 0.2 rejects any token that still carries `https://panopticon.dev/tenant_id`, including tokens that also carry the current claim. Reconfigure issuers and require fresh tokens before upgrading. Main validation keeps tested artifacts and does not create tags or GitHub releases. Stable publication uses a `vMAJOR.MINOR.PATCH` tag and is described in [docs/releasing.md](docs/releasing.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).

### Optional access events

`CPEDGE_API_ACCESS_EVENTS=true` requires `CPEDGE_EVENTS_URL` (events owner's base URL) and `CPEDGE_EVENTS_TOKEN` (a producer credential bound to `controlplane-edge`). Startup rejects missing configuration. Install the owner's `gateway_api_access_v1` contract before enabling delivery. Edge sends tenant-bound successful API/GraphQL access events to `/events`, with a matching idempotency key and event identity. Unscoped requests produce no tenant event. The payload contains only method, path and a generated trace identity, never queries, bodies or credentials. Delivery is best effort with a bounded queue and timeout; failures and queue overflow are logged. This is telemetry, not a durable audit log. It does not write a local outbox.

Canonical scope discovery and checks at `/api/v1/authority/*` and public
`/api/v1/networks/*` forward to User, which owns all current network/tenant/org
facts. A verified issuer identity can discover its contexts without an implicit
tenant; a caller-supplied tenant header cannot provide one. User still enforces
current subject authority. Private network/organization scope-check routes remain
under `/api/v1/internal/*` and are never exposed by Edge.

## Moving TEST runtime

Main qualification builds the stateless service image from the exact tested Edge
wheel. Its private runtime dependencies are the same digest-verified exact-source
wheel fixtures used by package qualification; public dependencies come from the
frozen runtime lock with required hashes. No Git credential enters the container
build. The final image runs as a non-root user with no database or migration
startup and is exercised with networking disabled and a read-only filesystem.

Successful current-main pushes advance `ghcr.io/hyperme-sh/controlplane-edge/runtime:test`.
PR checks build and exercise a local image without publishing. Manual workflow
runs also stop before TEST publication. Revision/wheel labels and context digests
record provenance; they do not require pinning running services. Superseded builds
cannot advance the channel. This is a TEST service channel, not a production
release or deployment. Infra owns the separate moving-channel adoption and live
acceptance; no TEST fixture reset or reseeding is involved.

### Tenant object storage

`CPEDGE_STORAGE_SERVICE_URL` routes only `/api/v1/storage/objects`, `/api/v1/storage/records` and
`/api/v1/storage/tenant` to Spanopticon's storage-only process. An unset owner
returns 503; anonymous requests still fail authentication. The old
`/api/v1/storage/configure` and other retired monolith paths are not restored.
The storage process verifies operation scopes/current tenant administration.
Existing API-key exchange strips the raw key and forwards its bounded signed
bearer with the credential's tenant, preserving binary bodies and response
streaming. Storage is not added to OpenAPI discovery because its current process
does not expose an OpenAPI endpoint.

Storage bodies require one numeric Content-Length (empty GET/HEAD/DELETE may
omit it). Object PUTs allow at most 64 MiB; named record PUTs allow 8 MiB; administration
bodies allow 8 KiB. Record writes require `storage:records:write`, separately
from `storage:objects:write`. Conditional request headers and response ETags pass
through so callers can detect conflicting cache updates.
The proxy rejects compressed, oversized and length-mismatched bodies, limits
buffered storage requests to eight per worker, limits body reads to 30 seconds,
and limits the queue/read/upstream phase to 120 seconds. Tenant configuration
and deployment remain operator-owned; this setting does not provision storage.

The storage owner also accepts consume-only challenge replay calls at
`POST /api/v1/storage/replays/{namespace}/{nonce}`. Edge requires an exchanged
API-key session with `storage:replays:consume`, an empty body and one canonical
`X-Replay-Expires-At` Unix-seconds header. Other methods, mutable cache/object
scopes and ambiguous body/expiry headers are refused before forwarding. The
storage owner enforces expiry, atomic replay rejection and tenant isolation.
This route does not grant or provision an issuer credential.

### Visor bot credentials

The edge forwards scoped `hm_bot_` bearers only on POST requests to
`/api/v1/hypermesh/bots/{UUID}/agent/heartbeat`, `/claim`, and `/complete`, with
a valid tenant header and the proxy enabled. It does not manufacture JWT claims
or authenticate the bot itself. Hypermesh Plane checks the credential hash,
tenant/bot binding, revocation and assignment on each request. The ordinary rate
limit and upstream response status remain intact. Bot enrollment, listing,
assignment, control and task dispatch still require a verified owner session;
a bot bearer cannot call those operations or host/service routes.
