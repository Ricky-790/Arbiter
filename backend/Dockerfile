# syntax=docker/dockerfile:1

# Arbiter backend. One image runs both backend processes -- the FastAPI API and
# the Celery match worker -- and the command decides which:
#
#   API     (default)  uvicorn app.api:app --host 0.0.0.0 --port 8000
#   worker             celery -A app.workers.celery_app worker \
#                          --queues=arbiter.matches --concurrency=1
#
# Postgres and Redis are external: they are reached through DATABASE_URL and
# REDIS_URL, and no database or broker runs inside this image. On start the
# entrypoint brings the database up to date with Alembic, then runs the command.
#
# Required environment:
#   DATABASE_URL            Postgres, migrated on start
#   REDIS_URL               Celery broker and the match-event pub/sub channel
#   SOLARI_API_KEY          sandbox provider
#   NVIDIA_API_KEY, OPENROUTER_API_KEY, GOOGLE_API_KEY
#                           keys for the free models
#   ARBITER_BYOK_SECRET     encrypts user-supplied keys between API and worker
#   LOGFIRE_TOKEN           observability; the worker reads it at import
#
# Build from this directory:  docker build -t arbiter-backend backend/

FROM python:3.12-slim

# uv, pinned to the version this project's uv.lock was resolved with.
COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so this layer is reused until pyproject.toml or uv.lock
# change. The app itself is run from the copied source rather than installed,
# which keeps the image to a single copy of the code.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Normalise modes: files copied from the host can arrive owner-only (600),
# which the non-root user below would then be unable to import.
RUN chmod -R a+rX /app/app && chmod 755 /usr/local/bin/docker-entrypoint.sh

RUN useradd --create-home --uid 10001 arbiter
USER arbiter

# The API port. The worker needs no inbound port.
EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
