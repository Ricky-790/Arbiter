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
- prisoner activity inspection (`peek_prisoner_logs`)
- pass

The exact allowed tools are configured explicitly by `warden.py`.

The Prisoner activity log (`/tmp/prisoner_logs`) records only the Prisoner's
tool calls, never their results, and never private calls such as flag
submission or scratchpad use.

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

At most `MAX_ACTIVE_TRAPS` (2) traps may be armed and unresolved at once;
`TrapManager.validate_arm` rejects the third and says why, and a firing frees
its own slot. The Warden's instructions tell it to spend the two armings
carefully, so a rejected arming is a recoverable result it can see and respond
to — not something to soften into "always allow".

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
- the Prisoner activity log (tool calls only, never results or private calls)
- intentionally public match information

The Prisoner's home directory `/home/prisoner` is out of bounds, even though the
Warden's `NOPASSWD:ALL` root technically outranks its `0700` mode. That is why
the rule lives in the Warden's instructions rather than in a path check:
`peek_prisoner_logs` is the one sanctioned window into the Prisoner's side, and
trading on the Warden's root to read the Prisoner's files defeats the point of
the role. Do not add a tool-level path denylist to enforce it — it would fail
open exactly like the command denylist the Engine docs reject.

## Security

Warden privilege is sandbox-local.

Never expose Arbiter host credentials, backend resources, database credentials, provider keys, or host filesystem access to the Warden.
