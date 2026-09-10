# Prisoner Agent — Agent Instructions

## Role

The Prisoner is the offensive agent. Its objective is to accomplish the challenge goal before the match ends.

For the current V1 challenge, this means discovering the secret and submitting the correct flag.

## Implementation

`PrisonerAgent` extends `ToolChoosingAgent`.

The role-specific configuration currently controls:

- model name
- instructions
- objective
- scripted calls for tests
- allowed tools

The current allowed tool set is intentionally narrow. Check `prisoner.py` rather than assuming every registered tool is available.

## Rules

- Do not put match/game logic here.
- Do not directly call Solari.
- Do not directly access `SandboxManager`.
- Request actions through `ToolCall`.
- Treat tool results as observations, not as authoritative match state.
- Do not add hidden shared state between Prisoner and Warden.

If adding persistent memory, use the dedicated scratchpad capability rather than inventing another history mechanism.
