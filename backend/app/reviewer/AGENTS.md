# Reviewer — Agent Instructions

## Purpose

This package answers questions about a **finished match** so a human or an LLM
can propose a better strategy than the one it was played with.

It owns:

- reading a match, its events, its conversations and its end-of-match stats
- shaping that data into small, paginated, JSON-safe answers

It does **not** own match rules, scoring, or the improvement itself. It judges
nothing; it reports.

## Read-only, absolutely

**Nothing in this package may write.** No INSERT, UPDATE, DELETE, no
``session.commit()``, no side tables, no "review" rows. Every function is a
SELECT.

This is a hard boundary, not a convention. The reviewer is expected to be
exposed to an LLM as a set of tools, and the whole point of that agent is to
*look at* a match. If it could write, a bad strategy suggestion could become a
rewritten match history.

## No caller-supplied SQL

**Never accept SQL, table names, column names, or filter expressions as
arguments.** An agent driving these functions must be able to choose *which*
question to ask, never how it is spelled.

Every argument is a typed value or an enum-like string that is checked against a
known set (`actor`, `event_type`). Filters are built with SQLAlchemy
expressions over ORM columns, so values are bound, never interpolated.

Adding a new question means adding a new function here -- not a generic query
runner.

## Shape of the API

- **Many small functions, not one big one.** ``get_tool_calls``,
  ``get_agent_thoughts``, ``get_trap_events``, ``get_conversation`` and friends
  are deliberately separate: an LLM reviewer asks for the two or three it needs,
  and a full match never lands in one context window.
- **Every listing is paginated.** ``offset``/``limit``, a ``total`` and a
  ``has_more``, so the frontend and an agent can both walk a long match. The
  limit is clamped to ``MAX_LIMIT`` so one call cannot pull everything.
- **Return models, not ORM rows.** Everything returned is a Pydantic model from
  ``models.py``, so it is JSON-safe for both the API and a tool result.
- **Order is stable.** Listings order by ``(timestamp, id)``; without the id
  tie-break, two events sharing an instant can be skipped or repeated by paging.

## Reading the stored tables

- ``match_events`` is the source of truth for what happened. Tool calls, the
  agents' narration, and trap firings all come from there.
- ``matches.prisoner_stats`` / ``warden_stats`` are the Engine's end-of-match
  summary: credits, tool calls, and each side's own trap counters. They are
  written once and are ``None`` for older matches, so the totals prefer the
  stored value and fall back to counting ``match_events``. The per-tool and
  success/failure breakdowns are always counted from events, because they are
  breakdowns rather than totals.
- ``result`` on a ``trap_triggered`` row carries which trap fired, what it was
  watching (``target``) and the turn each side was on. The target is what tells
  two firings of the same trap tool apart; without it they are indistinguishable.
- ``match_agent_messages`` holds each agent's conversation as one JSONB column,
  so its page is taken in memory. There is nothing to push down.
- ``matches.strategy`` / ``strategy_id`` are the per-side record of what the
  match ran and what it was promoted to. ``MatchOverview`` reads them straight
  off the row, so a review reports the strategy the match *actually used*.
  ``AgentBriefing.strategy`` is the older, weaker source -- it is parsed back
  out of the opening prompt, so prefer the column when both are available and
  never treat a parse failure as "there was no strategy".

## Exposed over HTTP

``app/api/routes/strategy_review.py`` mounts these functions at
``/api/v1/reviewer``.
The routes are adapters only: they add no filtering, no shaping and no paging of
their own, and they call these functions rather than the database. Keep it that
way -- a new review question belongs here, so that the HTTP surface and the
future agent tools cannot drift apart.

## Never surface hidden reasoning

``get_agent_thoughts`` returns what an agent chose to report for the match log.
Arbiter does not capture, store or replay a model's private chain of thought, so
there is none to expose -- do not add a function that implies otherwise.

## Dependency direction

``reviewer -> db``. It reads tables; it does not import the Engine, the workers,
or the API. The one constant shared with the runtime
(``TRAP_TOOL_NAMES``) is duplicated rather than imported, because importing
``app.engine`` pulls the whole match runtime into a read-only reader; a test
asserts the two stay equal.
