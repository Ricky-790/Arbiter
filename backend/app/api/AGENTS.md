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

## BYOK keys

`POST /matches/start-match` receives optional `prisoner_api_key` /
`warden_api_key` body fields for BYOK models (`is_byok_model()`). The route must:

- require the key when that side names a BYOK model, and reject an unknown model
- hand the key straight to `app.secrets.store_api_key()` — never place it on the
  Celery message, the match row, a match event, a log line, or the response
- tell the worker *that* a key exists (`prisoner_byok` / `warden_byok`) and let
  it redeem the key by `match_id`

Store the key before enqueueing, so a misconfigured store fails the request
instead of leaving a match that can never build its agents.

Future endpoints may cover challenge discovery, match creation, match status, live events, and historical results.
