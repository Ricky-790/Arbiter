"""Health endpoints: the API's, and the worker pool's.

Both exist for the same reason -- a platform refuses to consider a service
healthy until it answers on its port -- so both are pinned here: the path to
configure, the body that names the service, and that neither consults the
database or the broker, so a dependency blip cannot fail a deploy.

The worker's endpoint is exercised over real HTTP rather than by calling the
handler, because the parts most likely to break are the ones a direct call
skips: the status line, the headers, and keep-alive.
"""

import http.client
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import urlopen

from fastapi.testclient import TestClient

from app.api.app import app
from worker_health import (
    DEFAULT_PORT,
    DEFAULT_SERVICE_NAME,
    HEALTH_PATH,
    HealthHandler,
    port,
    service_name,
)


class ApiHealthTests(unittest.TestCase):
    """The API's own health route, which Render probes on the web service."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_reports_the_api(self) -> None:
        response = self.client.get(HEALTH_PATH)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "arbiter-api"})

    def test_the_root_answers_too(self) -> None:
        """Render's default health-check path is `/`, so it must not 404."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_health_is_not_under_the_versioned_prefix(self) -> None:
        """A platform probes a literal path, so it cannot live under /api/v1."""
        self.assertEqual(self.client.get(HEALTH_PATH).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/health").status_code, 404)


class HealthConfigurationTests(unittest.TestCase):
    """How the worker's port and reported name are configured."""

    def test_port_follows_the_platform_environment(self) -> None:
        with patch.dict(os.environ, {"PORT": "12345"}):
            self.assertEqual(port(), 12345)

    def test_a_missing_port_falls_back(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(port(), DEFAULT_PORT)

    def test_a_broken_port_falls_back(self) -> None:
        for value in ("", "not-a-port"):
            with (
                self.subTest(value=value),
                patch.dict(os.environ, {"PORT": value}),
            ):
                self.assertEqual(port(), DEFAULT_PORT)

    def test_the_service_name_names_the_pool(self) -> None:
        with patch.dict(os.environ, {"ARBITER_SERVICE_NAME": "arbiter-fork-worker"}):
            self.assertEqual(service_name(), "arbiter-fork-worker")

    def test_a_blank_service_name_falls_back(self) -> None:
        with patch.dict(os.environ, {"ARBITER_SERVICE_NAME": "   "}):
            self.assertEqual(service_name(), DEFAULT_SERVICE_NAME)


class WorkerHealthHttpTests(unittest.TestCase):
    """The worker's health port, over a real socket."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
        cls.server_port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.server_port}{path}"

    def test_health_answers_healthy_and_names_the_service(self) -> None:
        with (
            patch.dict(os.environ, {"ARBITER_SERVICE_NAME": "arbiter-fork-worker"}),
            urlopen(self.url(HEALTH_PATH), timeout=5) as response,
        ):
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "application/json")
            self.assertEqual(
                json.loads(response.read()),
                {"status": "ok", "service": "arbiter-fork-worker"},
            )

    def test_the_root_also_answers(self) -> None:
        with urlopen(self.url("/"), timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["status"], "ok")

    def test_any_other_path_answers_too(self) -> None:
        """The catch-all is deliberate: a wrong check path must not fail a deploy."""
        with urlopen(self.url("/healthz"), timeout=5) as response:
            self.assertEqual(response.status, 200)

    def test_a_query_string_does_not_hide_the_path(self) -> None:
        with urlopen(self.url(f"{HEALTH_PATH}?probe=1"), timeout=5) as response:
            self.assertEqual(response.status, 200)

    def test_a_head_probe_gets_the_headers_and_no_body(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.server_port, timeout=5)
        try:
            connection.request("HEAD", HEALTH_PATH)
            response = connection.getresponse()

            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"")
            self.assertGreater(int(response.getheader("Content-Length")), 0)
        finally:
            connection.close()

    def test_an_unsupported_method_is_refused_not_answered_healthy(self) -> None:
        """Only GET/HEAD are implemented; a POST is a 501, never a silent 200."""
        connection = http.client.HTTPConnection("127.0.0.1", self.server_port, timeout=5)
        try:
            connection.request("POST", HEALTH_PATH)
            self.assertEqual(connection.getresponse().status, 501)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
