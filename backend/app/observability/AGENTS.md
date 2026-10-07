# Observability — Agent Instructions

## Purpose

`app/observability/` is Arbiter's observability boundary.

Arbiter uses Pydantic Logfire with OpenTelemetry.

Tracing is opt-in via `ENABLE_LOGFIRE_TRACING`; see "Tracing is opt-in" below.

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

### Leave Logfire's scrubber alone

`logfire.configure` is called with **no** `scrubbing` override, so Logfire's
default patterns (`password`, `secret`, `api[._ -]?key`, and more) stay active.
That default is a safety net, and it is easy to disable by accident:
`ScrubbingOptions.callback` is consulted for each match, and whatever it returns
*replaces* the matched value — so a callback returning `m.value` replaces the
match with itself and silently turns the whole default off. An earlier
`scrubbing_callback` here did exactly that.

Customise only by adding `extra_patterns`, or by redacting *further*: a callback
may return `None` (drop the match) or a replacement such as `"[redacted]"`.
Never return the matched value. `tests/test_observability.py` guards this.

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

## Tracing is opt-in

Export to logfire.dev is governed by `ENABLE_LOGFIRE_TRACING` and is **off
unless that variable explicitly turns it on**. An unset variable means off.

This is not just a preference. `logfire.configure()` with no token falls back to
an interactive terminal prompt, which raises `EOFError` with no TTY — so a
deployment with no Logfire credentials would otherwise fail at import, in a
container, before serving anything. Missing credentials must never be a boot
failure.

When the flag is on, `send_to_logfire` is set to `if-token-present` rather than
`True`, so an environment that opts in without a token exports nothing instead of
failing.

Never require a Logfire credential to boot. `tests/test_observability.py`
guards this by importing the package in a credential-free subprocess.

Local span output still prints to stdout/stderr regardless of the flag, so
container logs keep their traces either way.

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
