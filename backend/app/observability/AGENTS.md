# Observability — Agent Instructions

## Purpose

`app/observability/` is Arbiter's observability boundary.

Arbiter uses **Pydantic Logfire** for application and AI observability. Logfire is built on OpenTelemetry and has first-class instrumentation for Pydantic AI, including agent runs, model calls, tool calls, retries, errors, token usage, latency, and cost information.

The goal of this package is **not** to build a custom telemetry system. It exists to:

1. configure Logfire
2. provide a small Arbiter-specific observability facade where needed
3. record match-specific information that automatic instrumentation cannot know about
4. keep Logfire-specific implementation details out of the Engine, agents, and tools

## Why Logfire

Arbiter uses Pydantic AI heavily, so Logfire is a natural fit.

Pydantic AI can be instrumented directly with Logfire, allowing model and agent execution to appear as traces without manually wrapping every LLM call.

Logfire also provides:

- LLM/model call tracing
- token usage
- latency
- cost information
- tool call inspection
- retry visibility
- errors/exceptions
- application traces
- HTTP/database/infrastructure instrumentation through OpenTelemetry
- SQL-based querying of telemetry

Do not introduce Langfuse solely for LLM tracing.

Evaluation datasets, LLM-as-a-judge, prompt experiments, and similar evaluation workflows are **not part of Arbiter's current observability requirements**.

Arbiter is primarily an adversarial benchmark/game runtime rather than a traditional dataset-based LLM evaluation application.

If evaluation functionality is added later, it should be evaluated separately rather than making the observability layer depend on it.

## Architecture

The intended dependency direction is:

```text
                    Arbiter
                       │
        ┌──────────────┼──────────────┐
        │              │              │
      Engine         Agents        Sandbox
        │              │              │
        └──────────────┼──────────────┘
                       │
                       ▼
                observability/
                       │
                       ▼
                    Logfire
                       │
                       ▼
                OpenTelemetry
```

The rest of the application should depend on Arbiter's observability interface where custom events are needed.

Only this package should contain direct Logfire-specific application code unless automatic instrumentation requires initialization elsewhere.

## Automatic Pydantic AI instrumentation

Pydantic AI should be instrumented through Logfire rather than manually recording every model request.

Typical application initialization should configure Logfire and enable Pydantic AI instrumentation:

```python
import logfire

logfire.configure()
logfire.instrument_pydantic_ai()
```

The exact initialization location should follow the application's existing startup structure.

Do not add manual telemetry around every call to:

```python
await agent.run(...)
```

if Logfire's Pydantic AI instrumentation already captures the operation.

Automatic instrumentation should provide visibility into:

- agent runs
- model requests
- model responses
- token usage
- latency
- retries
- errors
- tool calls executed by Pydantic AI

## Arbiter-specific telemetry

Logfire automatically knows about LLM/application execution, but it does not automatically know all of Arbiter's game concepts.

The observability layer should therefore expose a small set of Arbiter-specific operations.

Conceptually:

```python
observability.start_match(...)
observability.record_match_event(...)
observability.record_tool_execution(...)
observability.record_sandbox_event(...)
observability.finish_match(...)
```

The exact API can change as implementation evolves.

Do not create wrappers for things Logfire already instruments automatically.

For example, do not create:

```python
observability.record_llm_call(...)
```

unless there is a specific Arbiter-specific reason to do so.

Pydantic AI + Logfire should handle normal LLM call instrumentation.

## Match traces

A single Arbiter match should be represented as one logical trace.

The trace should contain metadata such as:

```text
match_id
challenge
prisoner_model
warden_model
provider
environment/version
```

The trace should eventually make it possible to inspect something like:

```text
Match abc123
│
├── Prisoner agent run
│   ├── LLM generation
│   ├── bash tool
│   ├── LLM generation
│   ├── read_file tool
│   └── submit_flag
│
├── Warden agent run
│   ├── LLM generation
│   ├── bash tool
│   ├── trap tool
│   └── ...
│
├── sandbox events
│
└── match finished
    ├── winner
    ├── reason
    └── duration
```

The exact Logfire span hierarchy should follow OpenTelemetry/Logfire conventions rather than introducing a custom tracing model.

## Match metadata

Useful match-level metadata includes:

- `match_id`
- challenge ID/name
- Prisoner model
- Warden model
- provider
- match start time
- match end time
- winner
- finish reason
- match duration
- application version

Use structured attributes/metadata rather than embedding all information into human-readable log strings.

## Tool telemetry

The Engine is authoritative for tool execution.

When a tool is executed, the observability layer may record:

- `match_id`
- actor
- tool name
- duration
- success/failure
- exit code
- credits charged
- cooldown information
- failure category
- relevant metadata

Useful failure categories include:

```text
tool_not_found
tool_not_allowed
cooldown
insufficient_credits
invalid_arguments
execution_failure
provider_error
```

An Engine-rejected tool call should not be represented as a successful tool execution.

Where possible, distinguish:

```text
requested
authorized
executed
successful
failed
```

This makes later analysis of agent behavior much more useful.

## LLM telemetry

Normal LLM telemetry should come from Pydantic AI + Logfire instrumentation.

Useful fields include:

- provider
- model
- input tokens
- output tokens
- total token usage where available
- latency
- retries
- errors
- request/response information where safe

Do not manually calculate token counts if the provider already supplies authoritative usage information.

Different providers may expose different usage information. Missing values should remain missing rather than being fabricated.

## Agent concurrency

Prisoner and Warden execute concurrently.

Do not use mutable global state such as:

```python
current_match
current_agent
current_trace
```

to determine which telemetry event belongs to which match.

Always associate custom telemetry explicitly with:

```text
match_id
agent/actor
```

Use task-local/context propagation only where it is safe and supported.

## Match events

The Engine may eventually emit structured events such as:

```text
MATCH_STARTED
AGENT_LLM_STARTED
AGENT_LLM_COMPLETED
TOOL_STARTED
TOOL_COMPLETED
TOOL_FAILED
SANDBOX_EVENT
TRAP_TRIGGERED
AGENT_ERROR
MATCH_FINISHED
```

These are Arbiter concepts.

They should not require the rest of the application to understand Logfire's internal APIs.

A useful architecture is:

```text
Engine
   │
   ▼
Arbiter event
   │
   ├── Logger
   ├── Logfire
   ├── future WebSocket
   └── future database
```

This keeps the Engine from becoming tightly coupled to a specific telemetry backend.

## Sandbox telemetry

Sandbox events are especially useful for Arbiter because the sandbox is the actual game environment.

Potential events include:

- process started
- process stopped
- file created
- file modified
- file deleted
- network activity
- trap-triggering activity

Only record events that are actually available from the Solari integration.

Do not invent sandbox telemetry that the underlying provider cannot reliably observe.

## Security and secrets

Observability must not become a mechanism for leaking credentials.

Never send to Logfire:

- provider API keys
- BYOK API keys
- database passwords
- JWT secrets
- Solari credentials
- host environment secrets

Tool arguments and command output can potentially contain secrets discovered inside the sandbox.

Apply redaction or truncation where appropriate before recording them.

Remember:

> The sandbox is adversarial by design.

Therefore, arbitrary command output should not automatically be treated as safe telemetry.

## Large outputs

Agents may intentionally execute commands producing very large outputs.

Do not blindly send unlimited stdout/stderr to Logfire.

Use configurable limits.

A useful recorded representation can contain:

```text
success
exit_code
output_size
truncated
output_preview
```

For example:

```text
output_size = 18342 bytes
truncated = true
```

This keeps observability useful without turning a single `ls`, `find`, or log command into a huge telemetry payload.

## Observability must never affect the match

Telemetry is secondary to game execution.

If Logfire is temporarily unavailable:

```text
match continues
agent continues
tool execution continues
sandbox continues
match result remains valid
```

A failure to send telemetry must never cause:

```python
raise
```

to propagate into the match loop merely because Logfire is unavailable.

Telemetry errors should be caught and reported through normal application logging.

## Logging vs observability

Use the existing logger for immediate local debugging.

Use Logfire for structured traces and cross-component investigation.

Do not duplicate every ordinary log line into custom Logfire events.

The two systems serve different purposes:

```text
Logger
    -> local operational/debug output

Logfire
    -> structured traces, spans, metrics, LLM/tool observability
```

## V1 scope

The initial observability implementation should be small.

Priority:

1. configure Logfire
2. instrument Pydantic AI
3. associate agent/match metadata with traces
4. record match start/finish
5. record important Engine/tool events
6. capture token usage and latency automatically
7. record failures and retries
8. ensure telemetry failures cannot break matches

Do **not** build:

- an evaluation framework
- datasets
- LLM-as-a-judge
- custom experiment infrastructure
- a custom tracing backend
- a second telemetry database

Those are separate future concerns.

## Future benchmarking

Arbiter will eventually be able to use its telemetry as benchmark data.

Potential metrics include:

- Prisoner win rate
- Warden win rate
- time to solve
- number of actions
- number of successful tool calls
- failed tool-call rate
- credits consumed
- token consumption
- LLM latency
- provider failure rate
- timeout rate

These should initially be derived from recorded match telemetry rather than requiring a separate evaluation framework.

The distinction is important:

```text
Observability
    "What happened during this match?"

Benchmarking
    "How did this model perform across many matches?"

Evaluation
    "Does this model/system satisfy a predefined quality criterion?"
```

Arbiter currently needs the first two much more than the third.
