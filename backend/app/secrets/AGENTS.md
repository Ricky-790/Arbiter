# `secrets/` — Agent Instructions

## Purpose

This package owns everything that happens to a user-supplied (BYOK) provider
key while it is in Arbiter's hands, at both ends of its life:

- **in transit** from the browser to the API, encrypted with the deployment's
  RSA public key (`rsa_keys.py`, `gen_rsa_keys.py`)
- **at rest** between the API process and the worker process, encrypted with the
  deployment's symmetric passphrase (`byok_store.py`)

They are not alternatives. The first protects a key on the wire, where the
browser has no shared secret with the server; the second protects it across a
process boundary on the server, where both ends can hold a shared secret.

## Transport: the RSA public key

The browser fetches `GET /api/v1/crypto/public-key`, encrypts each `*_api_key`
field with RSA-OAEP(SHA-256), and sends the base64 ciphertext in the same field.
Only those fields are decrypted, in one place: `app.api.api_keys.decrypt_api_key`.
Every route that reads a key goes through it, so "decrypt only the api-key
fields" is a property of the code rather than a habit.

Rules for it:

- **Asymmetric on purpose.** A symmetric scheme would have to ship the
  decryption key to the browser, and anything that can decrypt is exactly what
  an interceptor wants. A public key can be handed to anyone.
- **Plaintext still works.** An unconfigured deployment, the README's `curl`
  flow, and a client that got a 503 from the public-key endpoint all keep
  working: a value that is not this deployment's ciphertext passes through
  untouched. Never make this a hard requirement without deciding what those
  callers should do instead.
- **The fallback is guarded by length, not by hope.** RSA-OAEP output is exactly
  the modulus width, so a value of any other length was never ciphertext. A
  value that *is* the right length but does not open is a rotated key, and it
  raises `RsaKeyError` instead of being passed to the provider as the key.
- **`gen_rsa_keys.py` only prints.** It generates a pair and writes two
  environment lines; it never touches a file, a database, or the running app.
  Never make the application generate its own keypair: a key that changes on
  restart silently invalidates every browser mid-flight.

## Rules

- **Never** put a key on the Celery message, in a database row, in a match
  event, in a log line, or in an HTTP response.
- **Never** assign a user key to an environment variable, and never read one
  from the environment. `ARBITER_BYOK_SECRET`, `ARBITER_RSA_PUBLIC_KEY` and
  `ARBITER_RSA_PRIVATE_KEY` are the deployment's own material and are the only
  environment inputs here.
- Entries are per `(match_id, side)`, so the Prisoner's key and the Warden's key
  never collide and one match can never read another's.
- `take_api_key()` reads and deletes in one step. A key exists in the worker
  only from that moment on.
- The TTL exists for a match that is queued and never started; it is not the
  primary cleanup path.
- The store fails loudly (`ByokStoreError`) when the deployment secret is
  missing or has been rotated, rather than silently serving nothing.
- **A key must not outlive the request on any failure path.** A start route
  stores both sides, writes the match row, then enqueues; if it gives up after
  the first `store_api_key`, nothing will ever redeem what landed, and the entry
  sits encrypted in Redis for the whole TTL. Both start routes therefore discard
  on *every* failure from the first store onward — a half-stored pair, a failed
  match row, a failed enqueue — not only on the enqueue failure.
  `tests/test_byok_key_lifecycle.py` drives each of those paths.

## Not this package's job

- deciding whether a model needs a key — that is
  `app.agents.agents_directory.is_byok_model()`
- validating the request body — that is the API route
- building models or agents — that is `app.agents.agents_directory`
