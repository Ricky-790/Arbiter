"""Minimal HTTP endpoint for platforms that insist a service binds a port.

The Celery worker has no inbound traffic of its own: the API talks to it through
Redis, never over HTTP. Render, however, requires a service to listen on the
port in ``$PORT`` before it will consider a deploy healthy, so the worker
container serves this instead of nothing.

It reports that the *process* is up, not that the queue is drained -- if Celery
exits, the container exits with it and the platform restarts the service.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: Platform-provided port. 10000 is Render's default for a web service.
DEFAULT_PORT = 10000

BODY = json.dumps({"status": "ok", "service": "arbiter-worker"}).encode("utf-8")


class HealthHandler(BaseHTTPRequestHandler):
    """Answers every path, so any health-check path the platform picks works."""

    #: Every response carries Content-Length, so keep-alive is safe.
    protocol_version = "HTTP/1.1"

    def _respond(self, *, include_body: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        if include_body:
            self.wfile.write(BODY)

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
