#!/bin/sh
set -eu
# Fresh Postgres has no tables; lifespan seed fails without migrations.
uv run --project /app/controlplane-edge python -m controlplane_db.startup
exec uv run --project /app/controlplane-edge python -m controlplane_edge.main
