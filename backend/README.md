# Arbiter Backend

## Setup

```bash
cp .env.example .env   # fill in model/Solari keys
uv sync
uv run alembic upgrade head
```

## Seed challenges

Loads the three starter scenarios (The Secret File, Unlock the Configuration,
Stop the Target Process). It is idempotent — fixed ids, so re-running updates
the rows in place:

```bash
uv run python -m app.db.scripts.seed_challenges
```

## Run

Redis is both the Celery broker and the live match-event bus:

```bash
docker run -d --rm --name arbiter-redis -p 6379:6379 redis:7-alpine
```

API:

```bash
uv run uvicorn app.api.app:app --reload
```

Match worker (V1 runs one match at a time — keep concurrency at 1):

```bash
uv run celery -A app.workers.celery_app worker \
    --queues=arbiter.matches --concurrency=1 --loglevel=INFO
```

Fork worker — a second pool on its own queue, only if you are building forks.
It never starts a match, and a deployment that does not use forks does not need
it running:

```bash
uv run celery -A app.workers.celery_app worker \
    --queues=arbiter.forks --concurrency=1 --loglevel=INFO
```

Celery does **not** auto-reload. Unlike the API (`--reload`), these processes
keep the code they started with, so every change under `app/engine/`,
`app/agents/` or `app/sandbox/` -- match rules, setup commands, prompts, tool
descriptions -- needs a worker restart before the next match. A match run
against a stale worker silently enforces the old rules: the giveaway is a tool
result quoting an error string that no longer exists in the source. Restart
*both* pools after such a change, or a fork will be rebuilt under the old rules.

## Deploy

Three images, one per process. Each is self-contained — none derives from
another — so a platform can build whichever service it needs:

| Dockerfile | Process | Queue |
| --- | --- | --- |
| `Dockerfile` | API (`alembic upgrade head`, then uvicorn) | — |
| `Dockerfile.worker` | Match worker | `arbiter.matches` |
| `Dockerfile.fork-worker` | Fork worker | `arbiter.forks` |

`Dockerfile.worker` and `Dockerfile.fork-worker` differ only in the default
`CELERY_QUEUES`. If your platform can set a service's environment, deploy the
fork worker from `Dockerfile.worker` with `CELERY_QUEUES=arbiter.forks` and skip
the third file.

Point every service's health check at **`/health`**:

| Service | Health check |
| --- | --- |
| API | `GET /health` served by FastAPI (`/` answers too) |
| Match worker | `GET /health` on the worker's `$PORT` |
| Fork worker | `GET /health` on the worker's `$PORT` |

Both are liveness only — neither touches Postgres nor Redis, so a dependency
blip cannot fail a deploy or start a restart loop. The workers' body names the
pool that answered (`arbiter-worker`, `arbiter-fork-worker`), so a check pointed
at the wrong service is recognisable instead of silently green. The worker
endpoint answers any path, so a wrong check path cannot fail a deploy either.

The fork worker deliberately does not need the model provider keys or
`ARBITER_BYOK_SECRET`: replaying recorded tool calls builds no agents, so it has
no reason to hold a credential it never uses.

Only the API runs migrations. Both workers assume the schema is current, so
start the API first on a fresh deployment.

## Start and spectate a match

`POST /api/v1/matches/start-match` queues the match and returns a `match_id`
immediately; the worker hosts it asynchronously.

```bash
curl -X POST http://localhost:8000/api/v1/matches/start-match \
  -H 'Content-Type: application/json' \
  -d '{"challenge_id": "<uuid>", "prisoner_model": "nvidia/glm-5.3", "warden_model": "google/gemini-3.1-flash-lite"}'
# -> {"match_id": "...", "status": "queued"}
```

`POST /api/v1/matches/spectate?match_id=...` streams that match's events as
Server-Sent Events. Every event carries its `match_id`, and the stream ends
after `match_finished`.

```bash
curl -N -X POST "http://localhost:8000/api/v1/matches/spectate?match_id=<uuid>"
```

Note: the spectator route is `POST` as specified, so the browser `EventSource`
API cannot be used directly — consume it with `fetch()` and a `ReadableStream`,
or a small SSE client that supports POST. Subscribers only receive events
published after they subscribe (Redis pub/sub has no replay).

## Match archive

Both list endpoints are paginated (`page`, `page_size`, default 20 / max 100)
and sorted by date (`sort=date_desc` or `date_asc`).

```bash
# One page of matches, newest first (default).
curl "http://localhost:8000/api/v1/matches/?page=1&page_size=20&sort=date_desc"

# One match's persisted events, oldest first (default).
curl "http://localhost:8000/api/v1/matches/events?match_id=<uuid>&page=1"

# Probe a match's event count without pulling every event.
curl "http://localhost:8000/api/v1/matches/events?match_id=<uuid>&page_size=1"
```

Responses are `{items, page, page_size, total, pages}`.

