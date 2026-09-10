"""Arbiter backend entry point."""

from app.observability import configure_observability

# Configure observability first, before any instrumented code runs.
# Requires the `logfire` package (`uv sync`) and authentication
# (`logfire auth`); degrades to local-only logging until then.
configure_observability()
