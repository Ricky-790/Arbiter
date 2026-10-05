"""Minimal HTTP endpoint for platforms that insist a service binds a port.

The Celery worker has no inbound traffic of its own: the API talks to it through
Redis, never over HTTP. Render, however, requires a service to listen on the
port in ``$PORT`` and answer its health check before it will consider a deploy
healthy, so the worker container serves this instead of nothing.

**``/health`` is the path to configure.** Every path answers, deliberately, so
the check path cannot be guessed wrong and fail a deploy; ``/health`` is simply
the one the platform config and this project's docs name. The body reports which
service answered, so a pool checking against the wrong worker is recognisable
instead of silently green.

It reports that the *process* is up, not that the queue is drained -- if Celery
exits, the container exits with it and the platform restarts the service. It
deliberately touches neither Postgres nor Redis: a dependency blip is not
something restarting this process fixes, and a health check wired to the broker
would turn a transient outage into a restart loop.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: Platform-provided port. 10000 is Render's default for a web service.
DEFAULT_PORT = 10000

#: The health-check path to configure, on this service and on the API.
HEALTH_PATH = "/health"

#: Names the service in the health body. Each worker image sets it, so the
#: match worker and the fork worker do not answer with the same name.
SERVICE_NAME_ENV = "ARBITER_SERVICE_NAME"
DEFAULT_SERVICE_NAME = "arbiter-worker"


def service_name() -> str:
    """The reporting name for this process, or the generic default."""
    return os.environ.get(SERVICE_NAME_ENV, "").strip() or DEFAULT_SERVICE_NAME


def body() -> bytes:
    """The healthy response: this process is serving, and which one it is."""
    return json.dumps({"status": "ok", "service": service_name()}).encode("utf-8")


class HealthHandler(BaseHTTPRequestHandler):
    """Answers every path, so any health-check path the platform picks works."""

    #: Every response carries Content-Length, so keep-alive is safe.
    protocol_version = "HTTP/1.1"

    def _respond(self, *, include_body: bool) -> None:
        payload = body()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if include_body:
            self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._respond(include_body=True)

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._respond(include_body=False)

    def log_message(self, *args: object) -> None:
        """Keep the worker's log free of a request line per health check."""


def port() -> int:
    try:
        return int(os.environ.get("PORT", DEFAULT_PORT))
    except (TypeError, ValueError):
        return DEFAULT_PORT


def main() -> None:
    # Threaded so one slow probe cannot block the next, and reuse the address
    # so a fast redeploy does not trip over a socket still in TIME_WAIT.
    ThreadingHTTPServer.allow_reuse_address = True
    with ThreadingHTTPServer(("0.0.0.0", port()), HealthHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
