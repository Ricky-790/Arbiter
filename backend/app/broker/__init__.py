"""Redis-backed runtime transport for Arbiter.

This package owns the two Redis use-cases that sit between the HTTP API and
the match workers:

- the **match queue**: an API request is handed to a Celery worker instead of
  running a match inside the request/response cycle.
- the **match event stream**: every Engine event is published to a per-match
  Redis pub/sub channel so spectators can follow a live match over SSE.

Keeping both here means the API and the workers share one definition of the
channel names, payload envelopes, and queue/task names.
"""
