# Releasing controlplane-edge

Releases for this service are container images, tagged with channel or version tags only. There is no Python package, wheel, or prepared-snapshot distribution.

- TEST uses the `:test` channel tag.
- Production uses a version tag, and the `:prod` channel tag as the moving alias. Production release tags in Azure Container Registry stay write-protected, as described in [FyberLabs/infra#959](https://github.com/FyberLabs/infra/issues/959).

Public container publication and the remaining Apache repositories are tracked in [FyberLabs/infra#993](https://github.com/FyberLabs/infra/issues/993).

Pull-request and `main` checks still build and test the source, including any clean-source or secret scan already in those jobs, and then discard temporary distribution files. They do not retain or publish package artifacts.

The `0.2` runtime admission checks the exact version tag and builds its declared wheel for comparison. The stable GHCR publisher uses that admission and the matching qualified main runtime. Azure copies the same digest from the successful stable publisher run. Existing releases with a `runtime.json` asset remain valid sources for the Azure publisher.
