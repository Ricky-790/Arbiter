# `app/` — Agent Instructions

## Role

`app/` contains Arbiter's application domains:

- `agents/`: LLM agents and native deferred tool definitions
- `engine/`: authoritative match runtime
- `sandbox/`: Solari integration and sandbox lifecycle
- `observability/`: Logfire/OpenTelemetry telemetry boundary
- `api/`: HTTP/API adapters
- `db/`: persistence
- `logger/`: application logging

## Ownership

Put behavior in the domain that owns the concept.

- Match rules -> `engine`
- Agent/model interaction -> `agents`
- Tool capabilities/contracts -> `agents/tools`
- Sandbox execution -> `sandbox`
- Telemetry -> `observability`
- HTTP -> `api`
- Persistence -> `db`
- Local application logs -> `logger`

## Core runtime boundary

```text
Pydantic AI
    |
    | native deferred tool call
    v
Engine
    |
    | authorize + budget + game rules
    v
Tool
    |
    v
ToolExecutionContext
    |
    v
SandboxManager
    |
    v
Solari
```

The model must never bypass the Engine to execute a tool.

The Engine must never bypass `SandboxManager` to perform sandbox operations.

## V1

The current focus is the core Prisoner-vs-Warden runtime around deterministic developer-authored challenges.

Keep the implementation small and explicit. Avoid abstractions whose only purpose is to recreate functionality already provided by Pydantic AI or `SandboxManager`.
