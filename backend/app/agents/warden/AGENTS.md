# Warden Agent — Agent Instructions

## Role

The Warden is the defensive agent.

Its objective is to prevent the Prisoner from completing the challenge.

Its available capabilities may include:

- shell access
- file/process watching
- process termination
- automatic process-kill rules
- network blocking
- pass

The exact allowed tools are configured explicitly by `warden.py`.

## Implementation

`WardenAgent` is a thin specialization of the common agent runtime.

It configures:

- model
- role instructions
- allowed tools
- optional scripted calls for tests

Do not implement a second agent loop here.

## Tool interaction

The Warden receives native Pydantic AI tool definitions and requests actions through normal tool calls.

The Warden does not directly access:

- `SandboxManager`
- Solari
- Engine state

The Engine decides whether each requested capability is legal and applies credits, cooldowns, and trap rules.

## Traps

Trap state belongs to the Engine.

The Warden requests trap-related capabilities through tools. The Engine validates and arms them.

Sandbox events are observed by the sandbox layer and interpreted by the Engine.

Do not move trap state into the LLM agent.

## Scratchpad

Scratchpad use is voluntary.

The Warden may call:

```text
write_to_scratchpad(content)
```

to preserve useful observations or plans.

Do not force scratchpad writes.

## Information boundaries

The Warden must not receive the Prisoner's private reasoning or private scratchpad.

Its information comes from:

- its own tool results
- sandbox events exposed to it
- intentionally public match information

## Security

Warden privilege is sandbox-local.

Never expose Arbiter host credentials, backend resources, database credentials, provider keys, or host filesystem access to the Warden.
