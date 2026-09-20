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
