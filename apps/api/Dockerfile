# StockViz API — production image.
#
# Stage 1 installs the project (with uv) into a virtualenv; Stage 2 copies that
# venv + the source into a slim runtime image so the final image stays small.

FROM python:3.12-slim AS builder

# Install uv from its prebuilt image (no curl/network footwork needed).
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Cache dependencies first — this layer re-runs only when the lockfile changes.
# No BuildKit `--mount=type=cache` here: Railway's builder requires cache-mount
# ids to be prefixed `s/<service-id>-`, which is per-service and non-portable.
# The dependency set is small, so a cold `uv sync` per build is cheap enough.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Now bring in the source and install the project itself.
# README.md is required because pyproject.toml declares `readme = "README.md"`;
# hatchling reads it during the wheel build.
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY README.md ./README.md
RUN uv sync --frozen --no-dev


FROM builder AS test

# Install the dev group from the exact same lockfile/source used by the
# production builder. Tests are present only in this target, never runtime.
ENV PATH=/opt/venv/bin:$PATH
RUN uv sync --frozen
COPY tests ./tests

CMD ["pytest"]


FROM python:3.12-slim AS runtime

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src ./src
COPY --from=builder /app/migrations ./migrations
COPY --from=builder /app/alembic.ini ./alembic.ini

# Seed inputs for `stockviz.cli seed` / `backfill` on a fresh deploy — the
# company list and the split-unadjusted daily OHLCV history. News CSVs are
# left out (news comes from the live provider). ~5 MB.
COPY seed-data/companies.json ./seed-data/companies.json
COPY seed-data/stock-data-csv-files ./seed-data/stock-data-csv-files

# Run as a non-root user. Nothing here needs to write to the image at runtime,
# so the app owns only what it must.
RUN useradd --system --create-home --uid 10001 stockviz \
    && chown -R stockviz:stockviz /app
USER stockviz

# Render injects $PORT at runtime; default to 8000 for local docker runs.
ENV PORT=8000
EXPOSE 8000

# Same image, different command, for Kubernetes worker deploys:
#   uvicorn stockviz.main:app --host 0.0.0.0 --port 8000  # API (no migrations)
#   alembic upgrade head                                  # one-shot migrate Job
#   python -m stockviz.workers.scheduler                  # APScheduler singleton
#   python -m stockviz.workers.outbox_publisher           # outbox → Kafka
#   python -m stockviz.workers.trade_activity_consumer
#   python -m stockviz.workers.market_ingest_consumer
#   python -m stockviz.workers.market_analytics_consumer
#   python -m stockviz.workers.news_ingest_consumer
#   python -m stockviz.workers.news_sentiment_consumer
#   python -m stockviz.workers.sentiment_aggregate_consumer
#
# Run migrations on boot, then start uvicorn.
# Render's free tier doesn't support release commands, so we inline it here.
# Kubernetes MUST override this CMD so API replicas do not all migrate.
#
# --proxy-headers / --forwarded-allow-ips: behind Render's load balancer,
# request.client.host is the proxy for every request, so without these the
# rate limiter buckets every user together (see limiter.py).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn stockviz.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
