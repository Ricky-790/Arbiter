# Database — Agent Instructions

## Overview

`app/db/` contains Arbiter's PostgreSQL persistence layer.

- **Database:** PostgreSQL
- **ORM:** SQLAlchemy 2.x
- **Migrations:** Alembic
- All ORM models must be defined under `app/db/models/`.

The Engine remains the source of truth for live match state. The database stores persistent application state and match history.

---

## Tables

- `challenges`
- `matches`
- `match_events`
- `match_snapshots`
- `match_agent_messages`
- `strategies`

---

## `challenges`

Stores developer-authored challenge scenarios.

| Column           | Type                       | Constraints |
| ---------------- | -------------------------- | ----------- |
| `id`             | `UUID`                     | Primary key |
| `name`           | `VARCHAR`                  | Not null    |
| `description`    | `TEXT`                     | Not null    |
| `win_condition`  | `TEXT`                     | Not null    |
| `sandbox_config` | `JSONB`                    | Not null    |
| `files`          | `JSONB`                    | Not null    |
| `env_vars`       | `JSONB`                    | Not null    |
| `setup_script`   | `TEXT`                     | Nullable    |
| `created_at`     | `TIMESTAMP WITH TIME ZONE` | Not null    |
| `updated_at`     | `TIMESTAMP WITH TIME ZONE` | Not null    |

### Indexes

- Primary key index on `id`
- No additional indexes required initially

---

## `matches`

Stores one Prisoner-vs-Warden match.

| Column              | Type                       | Constraints                    |
| ------------------- | -------------------------- | ------------------------------ |
| `id`                | `UUID`                     | Primary key                    |
| `parent_match_id`   | `UUID`                     | FK → `matches.id`, nullable    |
| `branch_event_id`   | `UUID`                     | FK → `match_events.id`, nullable |
| `challenge_id`      | `UUID`                     | FK → `challenges.id`, not null |
| `prisoner_model`    | `VARCHAR`                  | Not null                       |
| `prisoner_provider` | `VARCHAR`                  | Not null                       |
| `warden_model`      | `VARCHAR`                  | Not null                       |
| `warden_provider`   | `VARCHAR`                  | Not null                       |
| `status`            | `VARCHAR` / Enum           | Not null                       |
| `winner`            | `VARCHAR` / Enum           | Nullable                       |
| `win_condition`     | `TEXT`                     | Not null                       |
| `duration_seconds`  | `FLOAT`                    | Nullable                       |
| `started_at`        | `TIMESTAMP WITH TIME ZONE` | Nullable                       |
| `finished_at`       | `TIMESTAMP WITH TIME ZONE` | Nullable                       |
| `created_at`        | `TIMESTAMP WITH TIME ZONE` | Not null                       |
| `prisoner_stats`    | `JSONB`                    | Nullable                       |
| `warden_stats`      | `JSONB`                    | Nullable                       |
| `strategy`          | `JSONB`                    | Nullable                       |
| `strategy_id`       | `JSONB`                    | Nullable                       |

### `prisoner_stats` / `warden_stats`

The Engine's end-of-match summary for one side, written once with the
`match_finished` event and `NULL` until then (and for matches recorded before
the columns existed):

```text
prisoner_stats = {"credits": int, "tool_calls": int, "times_trapped": int}
warden_stats   = {"credits": int, "tool_calls": int,
                  "traps_armed": int, "traps_triggered": int}
```

`credits` is what the side had left; `tool_calls` is how many actions it
requested, rejected ones included, so it matches that side's `tool_call` rows in
`match_events`. Calls replayed to rebuild a fork's sandbox are not counted.

The trap counters are each side's own: the Prisoner records how often it was
caught, the Warden how many traps it armed and how many of them landed. A
counter the other side owns is simply absent, so a reader cannot mistake it for
a real zero. Only successful armings count, and a firing increments both sides
at once.

JSONB rather than columns because more counters are expected over time and this
is a snapshot, not a query key. `app/reviewer/` reads it; nothing else queries
inside it.

### `strategy` / `strategy_id`

The approach each side was *started* with, and the library rows those approaches
were later promoted to. Both are keyed by side, because one match can carry a
strategy for the Prisoner and the Warden at once:

```text
strategy    = {"prisoner": str, "warden": str}
strategy_id = {"prisoner": "<uuid>", "warden": "<uuid>"}
```

`strategy` is written once when the match row is created, from the operator's
tips or from the library strategy a side was started with — the same text the
worker feeds the agent, so what ran and what is saved cannot drift. A side with
no strategy is absent rather than null; neither side having one stores `NULL`.

`strategy_id` records the `strategies.id` each side **ran**, and is written from
both ends of a strategy's life:

- at queue time, for a side the start request named a `*_strategy_id` for — the
  match is about to run that library strategy, so it says so
- by `POST /api/v1/strategies/save-strategy`, which writes the id of the row
  promoted out of this match

Both directions are needed for one question: *which matches ran this strategy?*
The text cannot answer it — it is copied onto each match, so two matches sharing
wording are unrelated — and with only the promotion write, a strategy's matches
would be just the single match it came from. Reading it means either side's
entry may name the strategy, so a query ORs over both keys.

It is keyed by side rather than a single FK because one match can carry a
strategy per side. Values are **strings**, because a JSONB object cannot hold a
native UUID; readers convert back.

Both are JSONB maps closed over the two sides. Do not add a third key without
deciding what reads it.

### `status` values

```text
queued
pending
starting
running
completed
failed
cancelled
```

A match row is created by `POST /api/v1/matches/start-match` with status
`queued`, moved to `running` by the worker when it picks the job up, and closed
out as `completed` or `failed` by the Engine — always the same row.

### `winner` values

```text
prisoner
warden
draw
```

`winner` is nullable until the match finishes.

`win_condition` is a snapshot of the challenge's win condition when the match is created.

### Indexes

Create indexes on:

- `challenge_id`
- `status`
- `winner`
- `created_at`

---

## `match_events`

Stores the persistent history of match actions and events.

| Column          | Type                       | Constraints                 |
| --------------- | -------------------------- | --------------------------- |
| `id`            | `UUID`                     | Primary key                 |
| `match_id`      | `UUID`                     | FK → `matches.id`, not null |
| `actor`         | `VARCHAR` / Enum           | Not null                    |
| `event_type`    | `VARCHAR` / Enum           | Not null                    |
| `action`        | `JSONB`                    | Not null                    |
| `result`        | `JSONB`                    | Nullable                    |
| `timestamp`     | `TIMESTAMP WITH TIME ZONE` | Not null                    |

### `actor` values

```text
prisoner
warden
system
```

### `event_type` values

Initial values:

```text
chat
tool_call
sandbox_event
match_started
match_finished
trap_triggered
agent_retry
agent_error
agent_unavailable
```

The schema should allow additional event types to be added later.

`action` and `result` use JSONB because chat and tool-call payloads have different structures.

A `tool_call` row's `result` carries the acting side's remaining `credits` after
that call, alongside `success`/`exit_code`/`error` and any `failure_category`.
It is the same balance the Engine attached to the agent's `ToolResult`, written
by `execute_tool_call()`; the API passes it through on `GET /matches/events` and
nothing recomputes it. See `app/engine/AGENTS.md` ("Both sides are told their
balance").

It also carries `stderr` whenever the command wrote any, **including on a
successful call**. A shell's exit code is its last line's, so a compound command
can succeed overall while an earlier line was refused; the stderr is the only
record of that, and it is persisted for the same reason it is shown to the
model.

Token counts and latency are provider telemetry and stay in Logfire; they are not stored in `match_events`.

### Indexes

Create indexes on:

- `match_id`
- `timestamp`
- `actor`
- `event_type`

A composite index on `(match_id, timestamp)` is preferred for efficient chronological match-event retrieval.

---

## `match_snapshots`

Indexes Solari snapshots of a match's reconstructed state, so a later fork can
boot from one instead of replaying history again.

| Column                   | Type                       | Constraints                                |
| ------------------------ | -------------------------- | ------------------------------------------ |
| `id`                     | `UUID`                     | Primary key                                |
| `match_id`               | `UUID`                     | FK → `matches.id`, not null, cascades      |
| `branch_event_id`        | `UUID`                     | FK → `match_events.id`, not null, cascades |
| `branch_event_timestamp` | `TIMESTAMP WITH TIME ZONE` | Not null                                   |
| `solari_snapshot_id`     | `VARCHAR(255)`             | Not null                                   |
| `created_at`             | `TIMESTAMP WITH TIME ZONE` | Not null                                   |

`match_id` is the match whose history the snapshot reproduces — the *source*
match being forked from, not the fork whose sandbox captured it — and
`branch_event_id` is how far along that history it goes. That pair is unique,
so two forks of the same point do not store the same state twice.

`branch_event_timestamp` duplicates the event's timestamp so "the newest
snapshot at or before event E" stays a single-table comparison. Rows are
deleted with their match. The snapshot bytes live in Solari, not here.

---

## `match_agent_messages`

One row per agent per match: the conversation that agent finished with.

| Column       | Type                       | Constraints                           |
| ------------ | -------------------------- | ------------------------------------- |
| `id`         | `UUID`                     | Primary key                           |
| `match_id`   | `UUID`                     | FK → `matches.id`, not null, cascades |
| `actor`      | `VARCHAR(32)`              | Not null (`prisoner` / `warden`)      |
| `messages`   | `JSONB`                    | Not null                              |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | Not null                              |

`messages` is a JSON-safe dump of pydantic-ai's `all_messages()`, loadable with
`ModelMessagesTypeAdapter.validate_python`. It is kept off `matches` so the
archive listing never reads it. `(match_id, actor)` is unique.

---

## `strategies`

The library the self-improvement loop grows: one reusable approach per side per
match, promoted out of a *finished* match rather than authored directly.

| Column                | Type                       | Constraints                            |
| --------------------- | -------------------------- | -------------------------------------- |
| `id`                  | `UUID`                     | Primary key                            |
| `match_id`            | `UUID`                     | FK → `matches.id`, not null, cascades  |
| `challenge_id`        | `UUID`                     | FK → `challenges.id`, not null         |
| `user`                | `VARCHAR(16)`              | Not null (`prisoner` / `warden`)       |
| `one_line_description`| `TEXT`                     | Not null                               |
| `strategy`            | `TEXT`                     | Not null                               |
| `origin_strat_id`     | `UUID`                     | FK → `strategies.id`, nullable         |
| `created_at`          | `TIMESTAMP WITH TIME ZONE` | Not null                               |

`(match_id, user)` is unique, so a match has at most one strategy per side and
promoting the same side twice is a no-op that keeps the first row — including
its `origin_strat_id`.

`strategy` is the text exactly as the match ran it, copied from
`matches.strategy[user]` — not sent by the caller, so the two cannot drift.
`one_line_description` is derived from that text (its first non-blank line,
truncated) rather than accepted as input.

`challenge_id` is denormalised from the match, so the library can be scoped to a
challenge without a join. A strategy is only meaningful against the challenge it
was played on; the API refuses to start a match from a strategy belonging to a
different one.

`origin_strat_id` is the strategy this one was evolved from, when the match was
itself started from a library strategy. It is a self-reference that clears on
delete rather than cascading, so lineage never takes descendants with it.

It is **not populated yet**. The input id is now recorded — a match started from
a strategy carries it in `matches.strategy_id` — so the ancestor is derivable,
but `save-strategy` takes only `match_id` and `user` and does not look it up.
Wiring it up means reading the parent match's `strategy_id[user]` at promotion
time; the column and the FK are already there.

> `user` is a reserved word in PostgreSQL. SQLAlchemy quotes it, so ORM and
> Alembic code is fine, but a raw `SELECT user, ... FROM strategies` resolves to
> the `USER` builtin. Write `"user"` in hand-written SQL.

### Indexes

`match_id`, `challenge_id`, `user`, `origin_strat_id`, `created_at`.

---

## Relationships

```text
Challenge 1 ──── N Matches
Match     1 ──── N MatchEvents
Match     1 ──── N MatchSnapshots
Match     1 ──── N MatchAgentMessages
Match     1 ──── N Strategies
Strategy  1 ──── N Strategies   (origin_strat_id)
```

SQLAlchemy relationships:

```text
Challenge.matches
Match.challenge

Match.events
MatchEvent.match
```

`MatchSnapshot`, `MatchAgentMessages` and `Strategy` are keyed by `match_id` but
expose no ORM `relationship()`; they are read one match at a time.

---

## Leaderboards

Do not create leaderboard tables.

Leaderboard statistics are derived from `matches`, grouped by:

```text
challenge_id
model
role
```

where `role` is `prisoner` or `warden`.

Derived statistics:

```text
games_played
wins
losses
win_rate
```

---

## Project Structure

```text
app/db/
├── models/
│   ├── __init__.py
│   ├── agent_message.py
│   ├── challenge.py
│   ├── match.py
│   ├── match_event.py
│   ├── match_fork.py
│   └── strategy.py
├── ...
```

Use SQLAlchemy 2.x typed ORM:

```python
Mapped[...]
mapped_column(...)
relationship(...)
```

All schema changes must be implemented through Alembic migrations.

---

## Persistence Rules

- The Engine is authoritative for live match state.
- Do not query the database on every tool call or agent action.
- Do not put game rules inside database models.
- Tools must not depend directly on the database.
- PostgreSQL stores application state and match history.
- Fork snapshots and agent message histories are written best-effort on the
  Engine's cleanup path; neither may fail a match that has already finished.
- Detailed LLM/tool telemetry remains in Logfire.
