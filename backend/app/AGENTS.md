# `app/` — Agent Instructions

## Role

`app/` contains Arbiter's application domains:

- `agents/`: LLM agents and tool capabilities
- `engine/`: authoritative match runtime
- `sandbox/`: Solari integration and sandbox lifecycle
- `observability/`: Langfuse telemetry boundary
- `api/`: HTTP/API adapters
- `db/`: persistence
- `logger/`: local logging

## Ownership

Put behavior in the domain that owns the concept.

- Match rules -> `engine`
- Agent decisions -> `agents`
- Tool capabilities -> `agents/tools`
- Solari operations -> `sandbox`
- Telemetry -> `observability`
- HTTP -> `api`
- Persistence -> `db`
- Human-readable application logs -> `logger`

## Dependency direction

```text
api -> engine
engine -> agents/tools
engine -> sandbox
engine -> observability
sandbox -> Solari
```

Lower-level packages should not import Engine game logic.

## V1

The current focus is the core Prisoner-vs-Warden runtime around a deterministic read-secret challenge. Avoid adding infrastructure that is not needed for the core match loop.
