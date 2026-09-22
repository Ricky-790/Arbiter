# `agents/` — Agent Instructions

## Purpose

This package owns the LLM-controlled side of Arbiter:

- model/provider mapping
- Pydantic AI agent construction
- role-specific instructions
- native deferred tool definitions
- allowed-tool configuration
- agent-facing models and contracts

It decides **what an agent wants to do**.

It does not decide whether an action is legal in the match.

## Agent/runtime boundary

Agents use Pydantic AI's native tool-calling/deferred-tool mechanism.

The model is given actual tool definitions:

```text
bash(...)
read_file(...)
write_file(...)
write_to_scratchpad(...)
...
```

The model emits a native tool call. Pydantic AI passes deferred requests to the Engine-bound executor. The Engine validates and executes the request, then the result is returned to the model through the normal tool-call conversation.

```text
Model
  -> native tool call
  -> deferred handler
  -> Engine
  -> Tool
  -> SandboxManager
  -> result
  -> Model
```

Do not represent tool selection as a custom structured `ToolCall` output.

Do not implement a second manual request/resume loop around Pydantic AI.

## `base.py`

`ToolChoosingAgent` is the common Pydantic AI wrapper.

Its responsibilities are:

- resolve the configured model
- construct the Pydantic AI `Agent`
- expose the allowed registry tools as native external/deferred tools
- connect deferred tool requests to an Engine-provided executor
- maintain the agent's Pydantic AI message history across match turns/runs
- handle bounded provider-level retry behavior
- support scripted calls when required for deterministic tests

The class should not:

- execute sandbox operations directly
- deduct credits
- enforce match cooldowns
- decide winners
- inspect opponent state
- implement match lifecycle

## Tool definitions

Tool schemas should be native Pydantic AI tool definitions derived from the registered tools.

Do not maintain a second prompt-only tool description format.

`BaseTool.description` and the typed `execute()` signature are the source metadata used to construct the model-facing tool definition.

The model should not receive internal fields such as:

- `match_id`
- sandbox user identity
- Engine state
- credit balance unless intentionally exposed as game information
- internal execution context

## Tool results

Tool results should be returned through Pydantic AI's normal tool-result mechanism.

Do not manually rebuild tool history as a substitute for native tool messages.

Do not retain an unlimited custom `_observations` list merely to reconstruct what Pydantic AI already knows.

If application-level match history is needed for telemetry, store structured events in the Engine/observability layer rather than injecting redundant JSON history into every prompt.

## Scratchpad

Scratchpad use is voluntary.

The agent may call:

```text
write_to_scratchpad(content)
```

when it decides information is worth preserving.

Do not force a scratchpad write after large output.

Do not capture hidden chain-of-thought.

The Engine may read the actor's scratchpad between agent runs to expose persistent agent memory, but that read is not itself an agent action and is free.

## Provider errors

Use bounded retry behavior for retryable provider failures such as rate limits.

A provider failure must not bypass Engine cleanup or silently give the agent authority over match state.

The opponent and match timeout continue according to Engine policy while an agent is retrying.

## Prisoner and Warden

`prisoner/` and `warden/` should remain thin role-specific wrappers.

They configure:

- role instructions
- model
- objective
- allowed tools
- optional scripted calls for tests

Do not duplicate the agent runtime in these packages.

## No chain-of-thought

Never ask the model to provide private reasoning as a `reason` field.

Do not persist, replay, or expose hidden model reasoning.

For debugging and benchmarking, record structured actions, tool names, arguments where safe, results, timing, token usage, and match events.

## Refactoring target

During the deferred-tool migration, remove code that only supported the previous structured-output approach:

- custom `ToolCall` generation
- argument coercion used only to repair model JSON
- manual signature validation used only for model output
- prompt-based tool descriptions
- manual observation replay used to reconstruct tool conversations
- explicit "choose exactly one tool call" output contracts

Keep validation that is still necessary at the Engine authority boundary.
