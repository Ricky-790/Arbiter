# Observability

Logfire-backed observability boundary for Arbiter.

This package keeps Logfire-specific implementation details out of the Engine, agent classes, and tools. Engine/agents import from `app.observability` (the facade); only `logfire.py` here touches the Logfire SDK directly.

Setup (deferred until needed): `uv sync`, `logfire auth`,
`logfire projects use --org <org> <project>`, then run via `main.py`
(which calls `configure_observability()` first).

See `AGENTS.md` for the intended architecture and telemetry contract.
