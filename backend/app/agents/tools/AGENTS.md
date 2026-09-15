# Agent Tools — Agent Instructions

## Purpose

`agents/tools/` defines the capabilities that Arbiter exposes to LLM agents.

Tools are **capabilities**, not game rules.

The current registry includes:

- `bash`
- `read_file`
- `write_file`
- `write_to_scratchpad`
- `watch_file`
- `watch_process`
- `kill_process`
- `auto_kill`
- `block_network`
- `submit_flag`
- `pass`

The exact registry is defined by `registry.py`.

## Native tool calling

Tools are exposed to Pydantic AI as native external/deferred tool definitions.

The model calls them by their registered name and typed arguments.

Do not create a second JSON protocol such as:

```json
{
  "name": "bash",
  "arguments": {}
}
```

as the model's structured output.

Do not maintain prompt-only tool descriptions when the native Pydantic AI tool definition can provide the same schema.

## `BaseTool`

`BaseTool` should remain small and declarative.

It owns metadata:

- `name`
- `description`
- `allowed_agents`
- `cost`

and the typed `execute()` contract.

It must not own:

- match state
- credits
- cooldowns
- winner logic
- sandbox instances
- `match_id`
- model interaction

The `execute()` implementation should delegate through `ToolExecutionContext`.

## Execution boundary

The authoritative path is:

```text
LLM
  -> native deferred tool call
  -> Engine
  -> authorization/budget/trap checks
  -> EngineExecutionContext
  -> BaseTool.execute()
  -> ToolExecutionContext
  -> SandboxManager
  -> Solari
```

Tools never call Solari or `SandboxManager` directly.

## Credits and cooldowns

`ToolCost` is metadata.

The Engine owns credit deduction and action cooldowns.

Normal game-action tools are charged and paced by the Engine.

The following tools are explicitly free:

- `read_file`
- `write_file`
- `write_to_scratchpad`

These three must not consume credits or start the normal action cooldown.

This is intentional and must be preserved during refactoring.

A tool's cost must never be enforced inside the tool implementation.

## File vs scratchpad

Keep these capabilities distinct.

### `write_file(path, content)`

Writes a normal file inside the actor's sandbox workspace.

The path is validated/scoped by `SandboxManager`.

### `write_to_scratchpad(content)`

Writes the actor's private canonical scratchpad.

It has no path argument.

The backend derives the scratchpad location from the acting sandbox user.

Scratchpad use is voluntary. Never automatically write model output into the scratchpad.

## Tool results

Use `ToolResult` for structured tool results.

Preserve:

- success/failure
- stdout/output
- error/stderr where available
- exit code
- relevant metadata

Do not turn failed commands into successful results.

Do not put hidden reasoning into `ToolResult`.

## Registry

`ToolRegistry` is responsible for:

- registering tools
- looking up tools
- filtering tools by actor
- supplying the tool objects used to build native model tool definitions

It should not execute tools.

It should not enforce credits or cooldowns.

## Adding a tool

1. Define the typed tool class.
2. Set its allowed agents.
3. Set its `ToolCost`.
4. Implement `execute()` through `ToolExecutionContext`.
5. Register it.
6. Add a context method only if the capability needs one.
7. Add the Engine adapter/context implementation if required.
8. Add authorization and execution tests.

Do not add custom model-output parsing for a new tool.

## V1 security posture

Sandbox commands are game actions. Do not add generic dangerous-command filtering merely because a command looks dangerous.

The important V1 security boundaries are:

- Solari sandbox isolation
- no host secrets in the sandbox
- Engine-side authorization
- resource/time limits
- actor-specific filesystem permissions
- server-authoritative match results
