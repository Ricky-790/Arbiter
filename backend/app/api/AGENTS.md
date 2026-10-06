# API — Agent Instructions

## Current status

The API package is currently minimal. The core match runtime is the priority.

When expanding the API, treat it as an adapter around application/domain services rather than putting match logic directly in route handlers.

## Rules

- Validate external input with Pydantic models.
- Keep route handlers thin.
- Do not duplicate Engine authorization logic.
- Do not let HTTP concerns leak into Engine/Sandbox/Tools.
- Do not expose secrets in responses or logs. A credential field is any body
  field named `api_key` or `*_api_key`: FastAPI echoes the offending input in a
  422, so `is_secret_body_field` decides what `scrub_secret_validation_errors`
  drops. Match on the name pattern, never a hand-written list of the field names
  in use today — the list this replaced covered `prisoner_api_key` and
  `warden_api_key` and silently missed the plain `api_key` on `verify-model` and
  the strategy review.
- Match results must come from server-side Engine state.

## Health

`GET /health` answers a liveness probe: this process can serve HTTP. `/` answers
the same body, because that is Render's default health-check path and a 404 there
would fail a deploy. `routes/health.py` holds both.

It is deliberately **not** under `/api/v1`: a platform probes a literal path, and
a health check is infrastructure rather than versioned API surface. Moving it
under the prefix would make every configured check a 404.

It touches neither Postgres nor Redis. A dependency blip is not something
restarting this process fixes, and a check wired to the database turns a
transient outage into a restart loop. A check that must *prove* dependencies are
reachable is a readiness concern and belongs at its own endpoint.

The worker pools answer the same question from `worker_health.py`, which binds
their `$PORT` and reports which pool replied.

## Encrypted api-key fields

A browser encrypts every `*_api_key` field before sending it, so a provider key
is never in a request body in plaintext. `GET /api/v1/crypto/public-key`
(`routes/crypto.py`) publishes the key to do it with, as both a JWK and a PEM;
the JWK is the one to use, because WebCrypto imports it directly while a PEM
must be un-armoured and base64-decoded to DER first. RSA-OAEP with SHA-256, and
the response names both so a client does not have to guess.

A 503 from that endpoint means the deployment has not configured the keys, not
that it is down, and a client that sees it should send plaintext, which the
server still accepts.

On the way in, `app/api/api_keys.py:decrypt_api_key` is the **only** place a
field is decrypted. Every route that reads a key calls it — `_resolve_side`
(which gates both start routes), `verify-model`, and the strategy review — so
"decrypt only the api-key fields" is enforced by the code path rather than by
remembering to. Nothing else in a body is ever passed to the decryptor.

A plaintext field passes through unchanged, which is what keeps existing
callers working. A field that is the shape of this deployment's ciphertext but
does not open is a 400 naming the field; that is a rotated key or another
deployment's public key, and passing it to the provider would report the real
problem as a bad credential. See `app/secrets/AGENTS.md` for the full contract.

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

## Strategies

`POST /strategies/save-strategy` takes `match_id` and `user`
(`prisoner`/`warden`) and promotes that side's strategy out of the match into
the `strategies` library, then writes the new row's id back onto the match.

- The strategy text is read from `matches.strategy[user]`, never from the
  request, so what was saved is exactly what the match ran.
- `(match_id, user)` is unique: a repeat call returns the existing row and
  inserts nothing. The link back onto the match is still written, so asking
  again repairs a match whose `strategy_id` is missing.
- A match with no strategy for that side is a 400, not an empty row.

`start-match` and `start-from-fork` accept `prisoner_strategy_id` /
`warden_strategy_id` alongside the free-text suggestions. Resolution
(`_resolve_strategies`) runs **before** any key is stored or queued, so an
unusable id fails the request without leaving a match behind:

- a referenced strategy must exist (404) and belong to the match's challenge
  (400) — a strategy is only meaningful against the challenge it was played on
- an explicit id wins over suggestions sent for the same side
- the resolved text is both sent to the worker as that side's suggestions and
  written to `matches.strategy`, so the text that runs and the text that can
  later be promoted are the same string

Do not resolve strategy ids concurrently on one `AsyncSession` — it is not
concurrency-safe. Both ids are read in a single query.

`GET /strategies/all` lists the library, newest first, paged like every other
listing, and takes an optional `challenge_id` to narrow it to one challenge —
the usual question, since a strategy only means anything against the challenge
it was played on. An id that matches nothing is an empty page, not an error.
Each row carries `challenge_name` alongside `challenge_id`, joined in: the ORM
row has only the id, and the name is what makes the list readable.

That name is fetched by an explicit join, **not** through a
`Strategy.challenge` relationship. `Challenge.matches` is `lazy="selectin"`, and
eager loaders chain, so a relationship would make listing the library load every
match of every challenge it touched. The join keeps the whole endpoint to two
queries whatever the data looks like.

`GET /strategies?strategy_id=...` returns one strategy with its **lineage**: the
match it was promoted from, and a page of the matches started from it.

The lineage reads `matches.strategy_id`, which is written from both ends of a
strategy's life — at queue time for a side the start request named a strategy
for, and at promotion for the match a strategy came out of. Recording the id at
*start* is what makes "which matches used this" answerable at all; without it
the only match a strategy could be traced to is the one it came from. The
promoted-from match is excluded from the usage list, because it ran the wording
before the strategy existed and is the origin rather than a use.

Each match in the lineage carries only its models, challenge name and winner —
enough to tell runs apart without dragging a match's history into a list that
can be arbitrarily long.

`POST /strategies/review` runs the Strategy Reviewer over one match to propose a
better version of one saved strategy. It takes `strategy_id` and `match_id`,
plus `provider`/`model`/`api_key`: the reviewer is BYOK like every other model,
and the key goes in the body so it cannot reach a URL, a log or browser history.

- Everything is validated **before** the stream opens — unknown provider, a
  missing key, a model the provider does not serve, an unknown strategy or
  match, and a strategy that was played on a different challenge. A failure is
  then a plain 400/404 rather than an error frame halfway through a review.
- The response is `text/event-stream`: `review_started`, then a
  `review_tool_call`/`review_tool_result` pair per read the agent makes, then
  exactly one `review_finished` (carrying the strategy) or `review_error`.
- The stream sends `: keep-alive` comments whenever it would otherwise be idle
  for `REVIEW_KEEP_ALIVE_SECONDS` (15s). This is not cosmetic: a provider retry
  is a 45s silence, and a connection dropped for idling cancels the review — so
  without the comments a recoverable 429 becomes a lost run. Comments carry no
  `data:` line, so the client skips them and they are not frames.
- What streams is what the review *does*. It is never the model's private
  reasoning — see `agents/AGENTS.md`, which forbids capturing it.
- **Nothing is saved.** The strategy is returned as a proposal; promoting it is
  the separate, deliberate `POST /strategies/save-strategy`.

## Review endpoints

`app/api/routes/strategy_review.py` exposes `app/reviewer` over HTTP under
`/api/v1/reviewer`. These routes are pure adapters: the reviewer owns what may
be seen, how it is shaped and how it is paged, and the routes only parse the
query, map a missing match to 404, and compose the one summary that spans
several reads. Adding a review question means adding a reviewer function, never
a new filter here.

The split is by size, not by table. `/summary` carries everything bounded by the
match — the match row (challenge, strategy, outcome), both sides' totals, the
requested side's strategy and opening message. Everything that grows with the
*length* of a match is its own listing: `/conversation`, `/tool-calls`,
`/thoughts`, `/traps`, `/events`. No single call can pull a whole match.

`/summary` always answers with a **list**, one entry per side summarised, so its
shape never depends on the request:

- `user=prisoner` or `user=warden` returns exactly one entry.
- Omitting `user` returns both, Prisoner first. Every entry is scoped entirely
  to its own side — `stats`, `strategy`, `briefing` — with no opponent block, so
  comparing the sides is reading two entries of the same shape rather than
  one object with a requested/opponent split. `match` is the shared match row,
  and its `strategy` map carries both sides' text for context. One call answers
  the whole comparison, instead of two reads that could straddle a match still
  being written.

Rules for these routes:

- `match_id` and `user` (`prisoner`/`warden`) come from `MatchSide`; an unknown
  side is a 422 before the route body runs. `user` is optional on `/summary`
  only — every other route is scoped to one side and still requires it.
- Listings share one `offset`/`limit` pair, capped at the reviewer's own
  `MAX_LIMIT`, and answer with the reviewer's `Page` shape
  (`items`/`total`/`offset`/`limit`/`has_more`). The page vocabulary is
  deliberately the reviewer's, not `PaginationMeta`, so the HTTP answer and an
  agent tool result are the same object.
- A listing 404s on an unknown match rather than returning an empty page, so a
  reviewer can tell "this match did nothing" from "there is no such match".
- `event_type` on `/events` is checked against `EVENT_TYPES` and rejected with
  400, so a typo cannot read as "no events".
- These routes write nothing and take no caller-supplied SQL.

Future endpoints may cover challenge discovery, match creation, match status, live events, and historical results.
