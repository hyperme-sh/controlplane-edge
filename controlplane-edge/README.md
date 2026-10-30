# Gateway (controlplane API + OpenAPI aggregation)

The container runs the **controlplane-core** FastAPI app (`api` package) with migrations via `docker-entrypoint.sh`. Extracted-service prefixes are **reverse-proxied** (mount-less) to auth / user / acl / payment / marketplace / ai / api-keys / template / tennessee-windage / hypermesh. Leftover monolith routes stay local — see [docs/controlplane-edge-cutover.md](../docs/controlplane-edge-cutover.md).

## Aggregated OpenAPI (HTTP)

Phase 2 merges the monolith spec with each configured microservice’s `GET {base}/openapi.json`:

| Env (preferred) | Fallback alias | Default (unset) |
|-----------------|----------------|-----------------|
| `CPEDGE_AUTH_SERVICE_URL` | `AUTH_SERVICE_URL` | skip |
| `CPEDGE_USER_SERVICE_URL` | `USER_SERVICE_URL` | skip |
| `CPEDGE_PAYMENT_SERVICE_URL` | `PAYMENT_SERVICE_URL` | skip |
| `CPEDGE_ACL_SERVICE_URL` | `ACL_SERVICE_URL` | skip |
| `CPEDGE_MARKETPLACE_SERVICE_URL` | `MARKETPLACE_SERVICE_URL` | skip |
| `CPEDGE_AI_SERVICE_URL` | `AI_SERVICE_URL` | skip |
| `CPEDGE_API_KEYS_SERVICE_URL` | `API_KEYS_SERVICE_URL` | skip |
| `CPEDGE_TEMPLATE_SERVICE_URL` | `TEMPLATE_SERVICE_URL` | skip |
| `CPEDGE_TENNESSEE_WINDAGE_SERVICE_URL` | `TENNESSEE_WINDAGE_SERVICE_URL` | skip |
| `CPEDGE_HYPERMESH_SERVICE_URL` | `HYPERMESH_SERVICE_URL` | skip |
| `CPEDGE_HYPERMESH_GATEWAY_SERVICE_URL` | `HYPERMESH_GATEWAY_SERVICE_URL` | skip |
| `CPEDGE_TURN_SERVICE_URL` | `TURN_SERVICE_URL` | skip |
| `CPEDGE_ORACLES_SERVICE_URL` | `ORACLES_SERVICE_URL` | skip |
| `CPEDGE_PAYMENTS_SERVICE_URL` | `PAYMENTS_SERVICE_URL` | skip |

- `CPEDGE_OPENAPI_FETCH_TIMEOUT_S` — HTTP timeout per OpenAPI fetch (default `5`).
- `CPEDGE_EDGE_PROXY` — reverse-proxy extracted prefixes (default `true`).
- `CPEDGE_PROXY_TIMEOUT_S` — HTTP timeout per proxied request (default `30`).

Endpoints (on the **gateway** host, e.g. port 8000):

- `GET /v1/openapi.json` — merged OpenAPI 3.x
- `GET /v1/docs` — Swagger UI for merged spec
- `GET /v2/openapi.json`, `GET /v2/docs` — same pipeline (version label for future divergence)
- `GET /changelog/openapi?from=v1&to=v2` — structural diff summary (JSON)
- `GET /changelog/openapi.md?from=v1&to=v2` — same diff as **Markdown**

## Cross-cutting (Step 6)

| Env | Purpose |
|-----|---------|
| `CPEDGE_CORS_ORIGINS` | Comma-separated allowed origins; empty allows `*` (dev) |
| `CPEDGE_RATE_LIMIT_PER_MINUTE` | Per-tenant+user sliding window for `/api/v1`, `/graphql` |
| `CPEDGE_GRPC_ENABLED` | `true` to start the minimal `ContractEcho` gRPC server |
| `CPEDGE_GRPC_HOST` / `CPEDGE_GRPC_PORT` | Bind address (default `127.0.0.1:50051`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OpenTelemetry OTLP HTTP exporter (optional) |
| `OTEL_SERVICE_NAME` | Span resource name (default `panopticon-gateway`) |
| `CPEDGE_API_ACCESS_EVENTS` | `true` to publish `gateway_api_access_v1` via tenant event publisher (non-blocking) |

JWT + `X-Tenant-ID` are normalized on `request.state` for REST and GraphQL. Site machine tokens (`hm_site_…`) are not JWTs; the control-plane edge forwards them so hypermesh-service can verify (`/api/v1/auditor/v0/…`, `/api/v1/grants/v0/…`, `/api/v1/hypermesh/site-tokens/me`, `/api/v1/hypermesh/site/jobs`, `/api/v1/hypermesh/site/devices/{id}`). **API keys:** `X-Api-Key: <prefix>.<secret>` plus `X-Tenant-ID` (gateway validates via `api-keys-service` and mints a short-lived exchange JWT). Set `CPEDGE_API_KEYS_SERVICE_URL` and shared `API_KEYS_INTERNAL_TOKEN` / `API_KEY_EXCHANGE_JWT_SECRET` (see `docker-compose.yaml`). gRPC clients must send metadata `authorization: Bearer <jwt>` and `x-tenant-id: <uuid>`. Public paths include docs, merged OpenAPI, health, changelog, `/auth/login|callback|refresh`, the Stripe webhook path, unauthenticated `GET /api/v1/hypermesh/catalog` plus `GET /api/v1/hypermesh/classes` (public_sku=true only), and the Host agent door (`POST /api/v1/hypermesh/agent/enroll` with no Authorization — hypermesh-service checks the one-time `enroll_token` — plus heartbeat / job pull / job result / tunnel, where the service checks `device_secret` Bearer). Checkout, lease, chat, operator device mint, and router credentials stay authenticated. The edge proxy forwards the minted bearer (not the raw API key) to upstreams. Those two Hypermesh browse paths are listed on gateway `/openapi.json` at their live URLs so the marketing site does not need `/_upstream/hypermesh/…`.

Upstream failures are listed under `x-controlplane-edge-meta.fetch_errors` in the merged JSON; successful sources are listed under `x-controlplane-edge-meta.sources`.

**Merge rules:** see [`src/controlplane_edge/openapi_merge.py`](src/controlplane_edge/openapi_merge.py) — monolith paths unchanged; remote paths prefixed with `/_upstream/{service_id}`; tags prefixed with `[service_id]`; schema keys/refs namespaced with `{service_id}__`.
