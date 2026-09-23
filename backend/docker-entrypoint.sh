#!/bin/sh
# Bring the database in DATABASE_URL up to date, then run the container's
# command (the API by default, or the Celery worker). Postgres and Redis are
# external services reached through the environment; this image runs neither.
set -e

alembic -c app/db/alembic.ini upgrade head

exec "$@"
