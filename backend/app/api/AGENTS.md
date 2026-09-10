# API — Agent Instructions

## Current status

The API package is currently minimal. The core match runtime is the priority.

When expanding the API, treat it as an adapter around application/domain services rather than putting match logic directly in route handlers.

## Rules

- Validate external input with Pydantic models.
- Keep route handlers thin.
- Do not duplicate Engine authorization logic.
- Do not let HTTP concerns leak into Engine/Sandbox/Tools.
- Do not expose secrets in responses or logs.
- Match results must come from server-side Engine state.

Future endpoints may cover challenge discovery, match creation, match status, live events, and historical results.
