# Warden Agent — Agent Instructions

## Role

The Warden is the defensive agent. It attempts to prevent the Prisoner from completing the challenge.

The Warden can have defensive capabilities such as:

- watching files/processes
- killing processes
- automatic kill rules
- blocking network
- shell access
- pass

## Implementation

`WardenAgent` extends `ToolChoosingAgent`.

The Warden's allowed tool set is configured explicitly in `warden.py`.

The Warden must not receive the Prisoner's private reasoning. Its useful information should come from observable match/sandbox events, its own tool results, and any intentionally exposed public match state.

## Traps

Trap state belongs to the Engine (`engine/traps.py`), not the Warden agent.

The Warden requests a trap through a tool. The Engine validates and arms it. Sandbox events can then trigger the Engine's reaction window.

Do not move trap state into the LLM agent.

## Security

Warden capabilities may be privileged inside the sandbox, but privilege is sandbox-local. Never give the Warden access to Arbiter host credentials or host resources.
