# Database — Agent Instructions

## Current status

The database package is currently minimal. Persistence is intentionally not part of the core match loop yet.

When persistence is introduced, PostgreSQL is the preferred primary database because Arbiter's data is strongly relational.

Likely entities include:

- users
- challenges
- matches
- match participants
- match events
- tool calls
- LLM calls

Use JSON/JSONB-style payloads for flexible event metadata rather than introducing a document database solely for heterogeneous telemetry.

## Rules

- Database persistence must not become the source of truth during an active match.
- The Engine remains authoritative for live match state.
- Do not make tools depend on the database.
- Avoid database calls in tight per-action paths unless explicitly required.
- Keep persistence adapters separate from game rules.
