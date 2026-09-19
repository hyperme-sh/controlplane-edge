#!/bin/sh
set -eu
# Fresh Postgres has no tables; lifespan seed fails without migrations.
uv run --project /app/controlplane-edge alembic -c /app/core/lib/controlplane-db/alembic.ini upgrade head
exec uv run --project /app/controlplane-edge python -m controlplane_edge.main
