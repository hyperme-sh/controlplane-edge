# Releasing controlplane-edge

Package `controlplane-edge` is version **0.2.0**. `release-policy.json` and `.github/workflows/release.yml` record release line **0.2**. Stable tags use `vMAJOR.MINOR.PATCH`. [release-policy.md](release-policy.md) describes the shared compatibility manifest. The [Spanopticon release policy](https://github.com/hyperme-sh/spanopticon/blob/main/docs/releases.md) describes the manifest format. The version published from this repository is the version in `pyproject.toml`.

Version 0.2 rejects the retired tenant-claim URI `https://panopticon.dev/tenant_id`, including when `https://spanopticon.dev/tenant_id` is also present. Issuers send `https://spanopticon.dev/tenant_id`. If `tenant_id` is present as well, it must be the same UUID. Ship the upgrade after issuers are reconfigured and clients have new tokens.

## Main validation

A push to `main` runs [`.github/workflows/package.yml`](../.github/workflows/package.yml). The job runs `bash scripts/check-package.sh` with git credentials disabled and uploads two Actions artifacts, retained for 90 days:

- `tested-dist` — the exact wheel and source archive the job just built
- `test-results` — the JUnit files from that run

That workflow does not create a git tag or a GitHub Release.

Pull requests run [`.github/workflows/preparation.yml`](../.github/workflows/preparation.yml), which executes `bash scripts/check-package.sh --fixtures`. It uploads the tested wheel, source archive, contract evidence, and consumer JUnit results as the `prepared-dist` artifact (30-day retention). That job does not publish a release. The artifact shows what the pull request built. Adopting those bytes as a dependency baseline is a separate release.

## Development snapshots

GitHub prereleases named `test-<commit>` are development snapshots. The package version embedded in a snapshot does not reserve a stable version. Store artifact and consumer evidence for snapshots under `releases/qualification`, and mark the receipt as a non-stable snapshot. `releases/accepted/` and the repository variable `SPANOPTICON_RELEASE_BASELINE_SHA` are used only for an immutable stable GitHub release. The release guard checks the live release, the stable tag’s source commit, and asset digests. Relabeling a snapshot does not make it a stable release.

## Stable publication

[`.github/workflows/release.yml`](../.github/workflows/release.yml) runs on tags matching `v*`.

A stable release needs all of the following:

1. An explicit `vMAJOR.MINOR.PATCH` tag on the commit to publish.
2. The `tested-dist` artifact from a successful `package.yml` run of that same commit.
3. A candidate manifest at `releases/candidate/release.json` for component `controlplane-edge`, line `0.2`, matching the version in `pyproject.toml` and the contract digest of the built artifact.
4. An accepted baseline: `releases/accepted/release.json` plus contract files and immutable artifact references, and `SPANOPTICON_RELEASE_BASELINE_SHA` set to that baseline’s full 40-character commit SHA.

Admission is the reusable workflow `hyperme-sh/spanopticon/.github/workflows/component-release.yml`, called with `release-line` `0.2`. The publish job runs only after admission succeeds. It calls `hyperme-sh/.github/actions/release-channel` and publishes the bytes from `tested-dist`. The publisher checks the baseline and the artifact digests itself. A green caller job is not enough to publish.

`releases/candidate/release.json` names the component, version, contract digest, and artifact digest. Generating it does not publish a release and does not create an accepted baseline.

When the repository has no accepted stable release yet, admission reads the live GitHub release list and compares the package versions recorded in this repository with `releases/candidate`. That path applies only while the live release list has no stable release and the candidate inventory is complete. The publisher still validates the tested bytes before any first stable tag is published. Snapshots remain evidence of a development build.

Patch releases keep the published contract. Replacing an artifact that was already published at the same version is rejected. Record downstream consumer results next to the release evidence. Public repositories publish from GitHub-hosted Ubuntu 24.04. Private repositories publish from the self-hosted `debrunner` runners. The publish job is the workflow that receives `contents: write`. Package validation stays read-only and does not receive deployment credentials.
