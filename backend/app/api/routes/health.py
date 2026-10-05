"""Service health for the API process.

Deliberately outside ``/api/v1``: a platform health check is infrastructure, not
part of the versioned API surface, and Render probes the literal path it is
configured with. ``/health`` is the path to configure; ``/`` answers too because
it is Render's default, so an unconfigured service does not fail its deploy.

Liveness only. It touches neither Postgres nor Redis, because a dependency blip
is not something restarting this process fixes -- a health check wired to the
database turns a transient outage into a restart loop. A check that must prove
dependencies are reachable is a *readiness* concern and would belong at its own
endpoint, not here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])

#: Names the service in the health body, so the API is told apart from the
#: worker pools, which serve their own health port (`worker_health.py`).
SERVICE_NAME = "arbiter-api"


def _health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness for the platform's health check."""
    return _health()


@router.get("/")
async def root() -> dict[str, str]:
    """Render's default health-check path, answered with the same body."""
    return _health()
