# Agent Tools — Agent Instructions

## Purpose

This package defines the capabilities exposed to LLM agents.

Current registry includes capabilities for:

- shell execution
- file read/write
- scratchpad writing
- file watching
- process watching
- process killing
- automatic process killing
- network blocking
- flag submission
- pass

The exact registration is defined by `registry.py`.

## Core design

`BaseTool` is declarative:

- `name`
- `description`
- `allowed_agents`
- `cost`
- typed `execute()` signature

`tool_description()` derives model-facing argument information from the execute signature, so tool definitions do not need to be manually duplicated in prompts.

`ToolRegistry` provides lookup, per-agent filtering, and generated descriptions.

## Critical boundary

Tools must not:

- create `SandboxManager`
- know a `match_id`
- own cooldowns
- deduct credits
- decide the winner
- mutate match state directly

Instead:

```text
Tool
  -> ToolExecutionContext
  -> EngineExecutionContext
  -> SandboxManager
```

This keeps tools reusable and makes the Engine the authority.

## Tool costs

`ToolCost` is metadata. Tools do not deduct credits themselves.

The Engine checks affordability and deducts the cost before execution.

When adding a tool:

1. add its cost
2. define allowed agents
3. implement a typed execute method
4. register it
5. add the corresponding `ToolExecutionContext` method if needed
6. implement the Engine adapter
7. test authorization and failure behavior

## `write_file` vs `write_to_scratchpad`

Keep these as separate capabilities.

- `write_file(path, content)` writes normal agent workspace files.
- `write_to_scratchpad(content)` has no path argument and writes the actor's canonical private scratchpad.

The special scratchpad path must be derived by the backend, not trusted from model input.

## Results

Use `ToolResult` for structured results:

- `success`
- `output`
- `error`
- `exit_code`
- `metadata`

Preserve exit codes and stderr where possible. Do not make a failed shell command look successful merely because a later `echo` succeeded.

## V1 security posture

Commands inside the sandbox are game actions. Do not add generic dangerous-command filtering. The important security boundary is the Solari sandbox itself and the Engine's authorization of capabilities.
