# `secrets/` — Agent Instructions

## Purpose

This package owns the short-lived handoff of **user-supplied (BYOK) provider
keys** from the API process to the match worker process.

The API and the Celery worker are separate processes, so a key cannot simply be
held in memory. The contract is:

```text
POST /matches/start-match  (key arrives in the body)
    -> API encrypts it and stores it under the match id   [store_api_key]
    -> the queue carries only match id + a `*_byok` flag  (never the key)
    -> worker redeems it as it builds the agents          [take_api_key]
    -> entry is deleted on read; TTL is the backstop      [discard_api_keys]
```

## Rules

- **Never** put a key on the Celery message, in a database row, in a match
  event, in a log line, or in an HTTP response.
- **Never** assign a user key to an environment variable, and never read one
  from the environment. `ARBITER_BYOK_SECRET` is the deployment's own
  encryption passphrase and is the only environment input here.
- Entries are per `(match_id, side)`, so the Prisoner's key and the Warden's key
  never collide and one match can never read another's.
- `take_api_key()` reads and deletes in one step. A key exists in the worker
  only from that moment on.
- The TTL exists for a match that is queued and never started; it is not the
  primary cleanup path.
- The store fails loudly (`ByokStoreError`) when the deployment secret is
  missing or has been rotated, rather than silently serving nothing.

## Not this package's job

- deciding whether a model needs a key — that is
  `app.agents.agents_directory.is_byok_model()`
- validating the request body — that is the API route
- building models or agents — that is `app.agents.agents_directory`
