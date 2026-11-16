# Edge publication checks

Edge remains Apache-2.0, version 0.2.0. Original and rebuilt wheels verify
owner LICENSE and NOTICE bytes. Existing runtime behavior and moving GHCR
`runtime:test` publication remain unchanged.

The existing image preserves indexed installed dependency license text and owner
legal files. Missing text fails preparation. CI scans every image layer for
secrets, hosted-only content and source-bundle paths, then checks installed owner
and legal bytes offline. No third-party source archives are fetched or bundled.

History review covers reachable fetched origin branches, tags and HEAD, including
bounded archived wheel members, without executing historical code. Findings are
a review queue rather than publication clearance. Deleted/unreachable refs,
remote LFS data and external archives are outside this scan.

Retained-image review inventories tagged and untagged GHCR versions and inspects
Linux amd64 layers without running old images. Other platforms, deleted versions
and other registries are outside its scope. Inaccessible inventory is reported
as unavailable, never empty. Inventory and inspection must succeed after automatic
main publication. No visibility settings or historical bytes are changed.

Integration/e2e remains nightly. No Actions uploads or source bundles are added.
