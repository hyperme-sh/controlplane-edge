# Darwin public download reconciliation

Issue [#12](https://github.com/hyperme-sh/controlplane-edge/issues/12) predates
native adoption in [edge #14](https://github.com/hyperme-sh/controlplane-edge/pull/14),
merged at `13c9d98369692a78b4440d10c89cdd45378bb2d3`. Code and security reviews
completed on its source head `7f5802cab0da404b78b1e932b6f18a4f2a68994b` without
findings. The allowlist and regression tests are already present on current main
`28e2375fff64a6319ea0a45236f5f90a6a9bc3c2`; no duplicate port is needed.

Historical [Panopticon #726](https://github.com/FyberLabs/panopticon/pull/726)
is closed without merging. It provides source provenance, not a source-merge
receipt. [Host #175](https://github.com/FyberLabs/hypermesh-host/pull/175) merged at
`479f537b103ecba3a60f9c37c8d95ff609c365d1`. Portal #14 remains a separate owner
approval/continuation acceptance gate.

## Native behavior

Public GET permits the bounded test/prod release index, release metadata and the
explicit immutable artifact names, including Darwin arm64 installer and agent
and platforms.json. Existing tests reject private files, traversal, unsupported
Darwin amd64 and Windows targets, and mutation methods. Mocked upstream tests
preserve redirects, Location and cache policy for each allowed artifact. Actual
main [42395969825](https://github.com/hyperme-sh/controlplane-edge/actions/runs/42395969825)
succeeds. A fresh local `bash scripts/check-package.sh` also passes 344 matching
source/wheel/rebuilt-sdist cases with no skips, plus 33 tooling cases. Native qualification and the public check below are separate operations;
package tests do not call deployed providers.

## Public acceptance

The [read-only receipt](darwin-public-downloads-2026-11-07.json) records anonymous
HTTPS GETs through api.test.hyperme.sh. Existing TEST release `134-bbf5b13ed301`
(version 0.0.134) served the actual Darwin arm64 agent, installer and platform
metadata. Each SHA-256 matched checksums.txt. Private.env, Darwin amd64 and Windows
arm64 installer paths returned 401. The public edge reported source
`53f67c56188708a740ec36099d48e3258081ea85`, which includes the allowlist adoption;
this is distinct from the current source main above. No new runtime was deployed.

The check downloaded bytes without executing binaries. It verifies served-byte
consistency and public routing, not independent signature trust, owner approval,
physical qualification or production acceptance. No tag or release was created
or changed. Broader fleet work remains in edge #3/#4/#11 and portal #14.
