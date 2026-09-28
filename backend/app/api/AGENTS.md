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

## Model selection and BYOK keys

`GET /matches/models` returns the catalogue: each provider and the models it
offers, nested rather than flattened, because the picker chooses a provider and
then a model under it. Those models are **suggestions** — the picker also accepts
a pasted name.

`POST /matches/verify-model` answers whether a provider actually serves a given
model, using the caller's key. A model that cannot be confirmed comes back as
`exists: false` with a reason (`not_found`, `key_rejected`, `unreachable`) rather
than an HTTP error: it is an answer, not a failed request. The browser cannot ask
a provider directly — CORS blocks it, and sending keys from the page would expose
them — so this endpoint exists to do it server-side.

`POST /matches/start-match` and `POST /matches/start-from-fork` receive
`prisoner_provider` / `prisoner_model` (and the warden pair) plus
`prisoner_api_key` / `warden_api_key`. Every model is BYOK, so the route must:

- reject an unknown provider, via `join_model_name()`
- require a key for **both** sides — there is no keyless model
- confirm each model with its provider, and refuse when it cannot (fail closed:
  the worker claims a sandbox before the first model call, so an unconfirmed name
  would spend it on a failure). Both sides are checked concurrently
- hand each key straight to `app.secrets.store_api_key()` — never place it on the
  Celery message, the match row, a match event, a log line, or the response, and
  never echo a provider's own error text back (it can carry the key in a URL)
- queue the provider and model separately; the worker joins them into the
  canonical `provider:model` and redeems the keys by `match_id`

Store the keys before enqueueing, so a misconfigured store fails the request
instead of leaving a match that can never build its agents.

Future endpoints may cover challenge discovery, match creation, match status, live events, and historical results.
