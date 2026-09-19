FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY core/lib/controlplane-db ./core/lib/controlplane-db
COPY core/events ./core/events
COPY core/lib/controlplane-core ./core/lib/controlplane-core
COPY core/models ./core/models
COPY controlplane-edge ./controlplane-edge
COPY controlplane-edge/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
RUN uv sync --frozen --package controlplane-edge
ENV PYTHONPATH=/app/controlplane-edge/src:/app/core/lib/controlplane-core/src:/app/core/lib/controlplane-db/src
WORKDIR /app/controlplane-edge
ENTRYPOINT ["/docker-entrypoint.sh"]
