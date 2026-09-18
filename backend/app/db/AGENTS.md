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

V1 consists of three tables:

- `challenges`
- `matches`
- `match_events`

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
pending
starting
running
completed
failed
cancelled
```

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
| `input_tokens`  | `INTEGER`                  | Nullable                    |
| `output_tokens` | `INTEGER`                  | Nullable                    |
| `total_tokens`  | `INTEGER`                  | Nullable                    |
| `latency_ms`    | `FLOAT`                    | Nullable                    |
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
```

The schema should allow additional event types to be added later.

`action` and `result` use JSONB because chat and tool-call payloads have different structures.

### Indexes

Create indexes on:

- `match_id`
- `timestamp`
- `actor`
- `event_type`

A composite index on `(match_id, timestamp)` is preferred for efficient chronological match-event retrieval.

---

## Relationships

```text
Challenge 1 ──── N Matches
Match     1 ──── N MatchEvents
```

SQLAlchemy relationships:

```text
Challenge.matches
Match.challenge

Match.events
MatchEvent.match
```

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
│   ├── challenge.py
│   ├── match.py
│   └── match_event.py
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
- Detailed LLM/tool telemetry remains in Logfire.
