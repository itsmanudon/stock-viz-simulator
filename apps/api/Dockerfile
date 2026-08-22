# StockViz API — production image.
#
# Stage 1 installs the project (with uv) into a virtualenv; Stage 2 copies that
# venv + the source into a slim runtime image so the final image stays small.

FROM python:3.14-slim AS builder

# Install uv from its prebuilt image (no curl/network footwork needed).
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Cache dependencies first — re-runs only when the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now bring in the source and install the project itself.
# README.md is required because pyproject.toml declares `readme = "README.md"`;
# hatchling reads it during the wheel build.
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY README.md ./README.md
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.14-slim AS runtime

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src ./src
COPY --from=builder /app/migrations ./migrations
COPY --from=builder /app/alembic.ini ./alembic.ini

# Run as a non-root user. Nothing here needs to write to the image at runtime,
# so the app owns only what it must.
RUN useradd --system --create-home --uid 10001 stockviz \
    && chown -R stockviz:stockviz /app
USER stockviz

# Render injects $PORT at runtime; default to 8000 for local docker runs.
ENV PORT=8000
EXPOSE 8000

# Run migrations on boot, then start uvicorn.
# Render's free tier doesn't support release commands, so we inline it here.
#
# --proxy-headers / --forwarded-allow-ips: behind Render's load balancer,
# request.client.host is the proxy for every request, so without these the
# rate limiter buckets every user together (see limiter.py).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn stockviz.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
