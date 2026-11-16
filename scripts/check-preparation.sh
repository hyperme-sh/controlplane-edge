#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/check-package.sh --fixtures
python="${UV_PROJECT_ENVIRONMENT:-$PWD/.venv}/bin/python"
uv pip install --python "$python" --no-deps coverage==7.17.3
"$python" -m coverage run --branch --source=controlplane_edge.group_allocation_scope,controlplane_edge.group_wrap_scope -m pytest -q tests/test_group_allocation_scope.py tests/test_group_wrap_scope.py
"$python" -m coverage report --fail-under=100 --show-missing
