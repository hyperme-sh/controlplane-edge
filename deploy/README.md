# Public host-download runtime bridge

The extracted edge package does not yet own a qualified full application
composition. `Dockerfile.host-downloads` applies the owning repository's public
browse module to the exact deployed runtime image. It preserves all dependencies,
authentication composition, database revision, entrypoint and other service code.
The expected old module hash must match before copying. The only source delta is
the merged Darwin/platform-metadata GET allowlist; private files and mutation
methods stay protected. This bridge is not standalone extraction acceptance.

Build from a clean exact owner revision, recording that revision and the resulting
registry digest:

```sh
docker build --file deploy/Dockerfile.host-downloads \
  --build-arg OWNER_REVISION="$(git rev-parse HEAD)" --tag "$IMAGE" .
```

The build checks public/protected dispatch through the existing runtime's actual
public-path resolver and imports its full application. Run `scripts/check-package.sh`
for source, wheel and sdist HTTP-boundary tests. Publish the immutable image and
select its digest in the test-plane infra overlay; converge through the existing
serialized deployment lane. Keep `GIT_SHA` as the original full-runtime revision;
the separate owner labels identify this limited source update. Verify anonymous
Linux and Darwin downloads and protected paths at the real public endpoint after
deployment. No database migration, workload restart or hardware qualification is
claimed by these checks. Retire this bridge after full edge-runtime qualification.
