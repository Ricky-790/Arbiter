# `agents/` — Agent Instructions

## Purpose

This package owns the LLM-controlled side of Arbiter:

- agent implementations
- model/provider mapping
- agent-specific instructions
- tool declarations
- tool registry
- tool execution contracts
- agent-facing domain models

The package decides **what an agent wants to do**, not whether the action is allowed by the match.

## Main components

### `base.py`

`ToolChoosingAgent` is the common Pydantic AI wrapper.

It:

- resolves a model from `agent_mapper`
- creates a Pydantic AI `Agent`
- requests one structured `ToolCall`
- validates the requested tool against `allowed_tools`
- supports scripted calls for deterministic testing
- receives tool results through `observe_result`

Agent-local observations must remain instance-specific. Never use class-level mutable history.

### `agents_directory.py`

Maps friendly model names to configured Pydantic AI model instances/providers.

Current model/provider configuration includes Google, OpenRouter, and NVIDIA/OpenAI-compatible providers. API credentials come from environment variables.

Do not expose credentials to agent prompts or sandbox processes.

### `models.py`

Contains agent-facing enums such as `AgentType` and `ActionType`. These should remain domain models rather than gaining match execution behavior.

### `prisoner/` and `warden/`

These are thin specializations of `ToolChoosingAgent` that provide:

- role-specific instructions
- role-specific allowed tools
- defaults for model selection

Do not duplicate the core agent loop here.

## Tool philosophy

Tools describe capabilities. The Engine is responsible for:

- whether the tool exists
- whether the actor may use it
- cooldowns
- credits
- trap validation
- execution context
- match consequences

A tool must not independently decide match winners or mutate Engine state.

## Agent observations

The current implementation passes tool results back to an agent via `observe_result`.

The planned memory model is:

```text
ephemeral:
    latest relevant tool result

persistent:
    agent-owned scratchpad

environment:
    actual sandbox state
```

Do not retain unlimited raw tool history in every prompt. Large outputs should eventually be pruned while preserving concise metadata and allowing important information to be written to the scratchpad.

Prisoner and Warden scratchpads must be isolated.

## Model errors

Provider errors should not silently terminate the entire match.

Use bounded per-agent retry behavior for retryable provider failures such as rate limits. The opponent and match clock continue running during retries.

Invalid tool calls should return useful errors to the same agent so it can recover. Do not allow an invalid model output to bypass Engine authorization.

## No chain-of-thought

Do not capture, persist, or expose hidden model reasoning. Observability should record model inputs/outputs and structured actions only where appropriate.

## Adding a new agent

Prefer:

```python
class MyAgent(ToolChoosingAgent):
    ...
```

and configure role-specific instructions/allowed tools.

Do not create a second custom agent execution loop unless the behavior genuinely differs from the common contract.
