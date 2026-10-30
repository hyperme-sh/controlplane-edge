#!/bin/sh
set -eu
# Fresh Postgres has no tables; lifespan seed fails without migrations.
/app/.venv/bin/python -m controlplane_tenancy.startup
exec /app/.venv/bin/python -m controlplane_edge.main
