# Prisoner Agent — Agent Instructions

## Role

The Prisoner is the offensive agent.

Its objective is to complete the current challenge before the match ends.

For V1 read-secret, it must discover the secret and submit the correct flag.

## Implementation

`PrisonerAgent` is a thin specialization of the common agent runtime.

It configures:

- model
- role instructions
- objective
- allowed tools
- optional scripted calls for tests

The common Pydantic AI/deferred-tool runtime belongs in `agents/base.py`.

Do not create a separate agent loop here.

## Tool interaction

The Prisoner receives native tool definitions and requests actions through normal Pydantic AI tool calls.

It does not directly call:

- `SandboxManager`
- Solari
- Engine methods

The Engine remains authoritative for whether a requested action is allowed.

## Scratchpad

The scratchpad is voluntary persistent agent memory.

The Prisoner may use:

```text
write_to_scratchpad(content)
```

when it decides a discovery, plan, or other information is worth preserving.

Do not force scratchpad usage.

## Boundaries

The Prisoner has no root, so `/home/warden` is genuinely unreachable — mode
`0700` on the Warden's home, enforced by the OS, blocks `bash`, `read_file` and
`write_file` alike. The instructions say so, because an agent that keeps trying
burns turns and credits on a wall.

The Prisoner's `bash` output is also capped (`PRISONER_BASH_OUTPUT_CHARS`,
4000). The cap is the Engine's, not the tool's, and the result says how much was
dropped; see `app/agents/tools/AGENTS.md`.

## Rules

- Do not put match/game rules here.
- Do not determine the winner.
- Do not trust model claims of success.
- Do not receive Warden private reasoning.
- Do not create shared state with Warden.
- Do not capture hidden chain-of-thought.
