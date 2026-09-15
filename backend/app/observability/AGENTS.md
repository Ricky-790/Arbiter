# Observability — Agent Instructions

## Purpose

`app/observability/` is Arbiter's observability boundary.

Arbiter uses Pydantic Logfire with OpenTelemetry.

The package should:

1. configure Logfire
2. enable Pydantic AI instrumentation
3. expose a small Arbiter-specific telemetry facade
4. record match/game information that automatic instrumentation does not know
5. keep telemetry implementation details out of Engine, agents, and tools

Do not build a custom tracing system.

## Deferred tool calling

Pydantic AI is responsible for normal model/tool-call telemetry.

Agents use native deferred tool calls:

```text
model
 -> native tool request
 -> deferred handler
 -> Engine
 -> Tool
 -> result
 -> model
```

The Engine is authoritative for actual tool execution.

Observability should distinguish, where practical:

```text
requested
authorized
executed
successful
failed
```

A model requesting a tool does not mean the action was successfully executed.

## Match telemetry

A match should be identifiable by:

- match_id
- challenge
- Prisoner model
- Warden model
- provider
- application/environment version
- winner
- finish reason
- duration

Prisoner and Warden telemetry must remain distinguishable.

Do not use mutable global state such as `current_match` or `current_agent`.

## Automatic Pydantic AI instrumentation

Prefer Pydantic AI + Logfire instrumentation for:

- model calls
- agent runs
- native tool-call requests
- deferred tool interactions
- token usage
- latency
- provider errors
- retries

Do not manually wrap every `agent.run()` call when automatic instrumentation already provides the information.

Do not manually calculate token counts if the provider supplies authoritative usage data.

## Engine-specific events

The Engine may emit structured events for:

- match started
- match finished
- tool requested
- tool rejected
- tool executed
- tool failed
- sandbox event
- trap triggered
- provider/agent error

Useful tool attributes include:

- actor
- tool name
- duration
- success
- exit code
- credits charged
- cooldown information
- failure category

## Security

Never record:

- API keys
- BYOK credentials
- database passwords
- JWT secrets
- Solari credentials
- host environment secrets

Sandbox command output is adversarial and may contain discovered secrets.

Use truncation/redaction before recording arbitrary output.

Never treat telemetry as a trusted source of match truth.

## Large outputs

Do not send unlimited sandbox output to Logfire.

Prefer structured metadata such as:

```text
output_size
truncated
output_preview
exit_code
success
```

## Failure isolation

Telemetry must never affect match execution.

If Logfire is unavailable:

```text
match continues
agent continues
tool execution continues
sandbox continues
```

Telemetry errors should be handled as observability failures, not match failures.

## V1 scope

Keep observability small:

- configure Logfire
- instrument Pydantic AI
- associate match/actor metadata
- record important Engine/tool events
- capture token usage/latency automatically
- record errors/retries

Do not build:

- datasets
- LLM-as-a-judge
- experiment infrastructure
- custom evaluation framework
- custom tracing backend
