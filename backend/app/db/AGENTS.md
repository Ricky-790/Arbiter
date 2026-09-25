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

## Relationships

```text
Challenge 1 ──── N Matches
Match     1 ──── N MatchEvents
Match     1 ──── N MatchSnapshots
Match     1 ──── N MatchAgentMessages
```

SQLAlchemy relationships:

```text
Challenge.matches
Match.challenge

Match.events
MatchEvent.match
```

`MatchSnapshot` and `MatchAgentMessages` are keyed by `match_id` but expose no
ORM `relationship()`; they are read one match at a time.

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
│   └── match_snapshot.py
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
