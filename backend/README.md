# Arbiter Backend

## Requirements

- Python 3.12 (pinned in `.python-version`) and [uv](https://docs.astral.sh/uv/)
- Docker, for Postgres and Redis
- A sandbox provider key: `E2B_API_KEY` 

## Setup

```bash
cp .env.example .env   # fill in api keys after
uv sync
source .venv/bin/activate
```

### Postgres and Redis

Both run in Docker.

```bash
docker run -d --name arbiter-postgres \
    -e POSTGRES_PASSWORD=password \
    -p 5432:5432 postgres:16

docker run -d --name arbiter-redis \
    -p 6379:6379 redis:7-alpine
```

To stop them:

```bash
docker stop arbiter-postgres arbiter-redis
```

### Migrations

Alembic lives in `app/db/`, so cd into it before running alembic commands.

```bash
uv run alembic -c app/db/alembic.ini upgrade head
```

The connection string is read from `DATABASE_URL` at migration time.

### Seed the challenges

Loads the three starter scenarios (The Hidden Artifact, Unlock the Configuration,
Stop the Background Task). It upserts on fixed ids, so re-running updates the
rows in place rather than duplicating them.

```bash
uv run python -m app.db.scripts.seed_challenges
```

## Run

Three processes. The API serves HTTP; the workers host matches.

API:

```bash
uv run uvicorn app.api.app:app --reload
```

Match worker runs one match at a time for now, so keep concurrency at 1:

```bash
uv run celery -A app.workers.celery_app worker \
    --queues=arbiter.matches --concurrency=1 --loglevel=INFO
```

Fork worker — a second pool on its own queue, only if you are building forks. It
never starts a match, and a deployment that does not use forks does not need it
running:

```bash
uv run celery -A app.workers.celery_app worker \
    --queues=arbiter.forks --concurrency=1 --loglevel=INFO
```

Restart *both* workers any changes in code.

## Optional: Logfire tracing

Off by default. Nothing is exported unless you ask for it, and no Logfire
credentials are needed in that case:

```bash
ENABLE_LOGFIRE_TRACING=0
```

Set it to `1` and add a write token to export traces:

```bash
ENABLE_LOGFIRE_TRACING=1
LOGFIRE_TOKEN=pylf_v1_...
```

Traces are one match per trace, with `match_*` spans for agent and tool calls and
`arbiter.*` attributes linking them to the match and the acting side. API keys
are never recorded, and Logfire's default secret scrubbing is left in place.

**A token is required when tracing is on.** With `ENABLE_LOGFIRE_TRACING=1` and no
`LOGFIRE_TOKEN`, Logfire falls back to an interactive prompt for credentials,
which fails with `EOFError` anywhere there is no terminal — a container, a cron
job, a CI run. Either set a token or leave the flag at `0`.

Span output still prints to stdout/stderr regardless of the flag, so container
logs keep their traces either way.

## Encrypted api-key fields

The browser encrypts each `*_api_key` field before sending it, using a public key
the API publishes at `GET /api/v1/crypto/public-key`. Generate the pair once per
deployment and put both values in the server's environment:

```bash
uv run python -m app.secrets.gen_rsa_keys
```

It prints two ready-to-paste lines:

```
ARBITER_RSA_PUBLIC_KEY=<base64 of the public PEM>
ARBITER_RSA_PRIVATE_KEY=<base64 of the private PEM>
```

Base64 is the default because a PEM has newlines; `--pem` prints the text
instead if your environment prefers it. Both forms load, and setting only the
private key is enough — the public half is derived from it. `--bits` (2048 by
default) sizes the modulus; RSA-OAEP with SHA-256 leaves room for a 190-byte
payload at 2048 and 446 at 4096, either of which fits a provider key.

**Keep the private value secret.** It is the deployment's decryption key, so
anywhere it is read by someone else — a shell history, a ticket, a build log — the
transport is compromised. Rotating it is safe: a browser holding the old public
key gets a 400 telling it to re-fetch, and nothing already stored is affected.

With neither value set the transport is simply **off**: the endpoint returns 503,
and api-key fields are taken as plaintext exactly as before. That is what keeps
the `curl` examples below working, so the encryption can be adopted by the
frontend without a coordinated backend change.

## Tests

```bash
uv run pytest tests/ -q
```

Observability tests use an in-memory OTel exporter, so no network, no sandbox,
and no real LLM calls.
