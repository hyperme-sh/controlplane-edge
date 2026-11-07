# Closure routing and dependency-access adoption

The native code/CI criteria of edge #2 and #18 are complete. The edge uses public
immutable dependency pins and credential-free package qualification; its closure
and single-credential changes are adopted with source, installed-consumer and
running-byte evidence. Live account-closure activation remains separate.

## Dependency access (#2)

All nine repositories named in #2 are currently public: controlplane-api, core,
tenancy, identity, db, events, user-service, controlplane-models and controlplane-proto.
No private-read credential or new runner grant is necessary for this graph.
Main package CI is enabled with read-only contents and immutable action/dependency
pins. Its package step disables Git credential configuration and unsets ambient
GitHub/dependency tokens. Public jobs use Ubuntu; private callers preserve the
`[self-hosted, linux, x64, debrunner]` policy. The separate PR preparation lane uses
verified fixtures and has no deployment credential.

Actual main [42347980219](https://github.com/hyperme-sh/controlplane-edge/actions/runs/42347980219)
at `2a7ad0c704e73e6f2675a54fa38c8dbafd1f9246` passes 334 matching source, installed-wheel
and rebuilt-sdist cases without skips. The downloaded archive and JUnits were
independently verified in [merged evidence #440](https://github.com/FyberLabs/infra/pull/440).
This intentionally replaces the old disabled/private-token premise; it does not
weaken private dependency access controls or supply deployment credentials.

## Closure and one verified credential (#18)

| Historical source | Destination and checks |
| --- | --- |
| Panopticon #671/#672 | `closure_auth.py` accepts native self credentials only on exact closure routes; operator trust requires an explicit validated client allowlist and dedicated native validator. Empty/malformed trust, API-key-derived subjects, unverified development fallback and private internal paths are denied. |
| Panopticon #702 | Policy rejects dual credentials before validation, including empty/malformed combinations. API-key requests become one signed exchanged identity and the raw key is removed. Closure forwarding strips caller attribution before reaching private authority. |

Native adoption commit `7f3b04c3c343285c75ec6935941a610700dbc2f3` added the owner
routing and real installed user-service consumer. Reviewed main
`28ee712111756c3886f6ebfd42f2607229b4dd44` preserves neutral owner composition and
independent security fixes. Canonical edge/identity namespaces and immutable owner
pins remain in the package metadata and lock. Four installed-consumer cases prove
that private self/operator/hold forwarding retains the original native bearer
without caller-controlled tenant/actor/lifecycle headers. Current targeted closure and
credential suites pass 33 cases, within the full 334-case matrix above.

[Infra #439](https://github.com/FyberLabs/infra/pull/439) deployed the reviewed route
image through [successful serialized convergence](https://github.com/FyberLabs/infra/actions/runs/42346793715).
All 33 installed edge runtime/resource files match the verified wheel, which is
byte-identical to current qualified main. The public mutation/console checks in
[#440](https://github.com/FyberLabs/infra/pull/440) establish their stated surface;
they are not live closure mutation acceptance. Public closure, worker and authority
actions remain off, as independently read back. No private authority, provider,
production or release activation is implied by closing this source-adoption audit.

Adoption audit: [spanopticon #7](https://github.com/hyperme-sh/spanopticon/issues/7).
Remaining edge cookie/site-token, independent integration and public rollout issues
retain their own acceptance criteria. No tags/releases, reviewer requirements,
branch protections or environment approval rules are introduced.
