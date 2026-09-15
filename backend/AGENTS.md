# Arbiter Backend — Agent Instructions

## Purpose

`backend/` contains the Python runtime for Arbiter, an AI-vs-AI adversarial sandbox platform.

A match places two LLM-controlled agents in an isolated Solari sandbox:

- **Prisoner**: attempts to complete the challenge objective.
- **Warden**: attempts to prevent the Prisoner from completing it.

Arbiter is an **agent harness and game runtime**. Pydantic AI is responsible for the agent/model interaction; Arbiter is responsible for the environment, rules, authorization, budgets, execution, evaluation, and lifecycle.

## Architecture

```text
Agent / Pydantic AI
        |
        | native deferred tool call
        v
      Engine
        |
        | authorize / budget / game rules
        v
      Tool
        |
        v
ToolExecutionContext
        |
        v
SandboxManager
        |
        v
   Solari Sandbox
```

The important invariant is:

> **The agent chooses. The Engine authorizes. The Tool delegates. The SandboxManager executes.**

### Domains

```text
agents/
    LLM/model integration
    native deferred tool definitions
    role-specific instructions
    tool declarations/contracts

engine/
    match state
    lifecycle
    timing
    credits
    cooldowns
    trap rules
    authorization
    win/loss conditions
    agent concurrency

sandbox/
    Solari integration
    sandbox lifecycle
    command/file/process/network operations
    sandbox monitoring and events

observability/
    Logfire/OpenTelemetry
    match/tool telemetry
```

Dependency direction:

```text
api -> engine
engine -> agents/tools
engine -> sandbox
engine -> observability

agents/tools -> ToolExecutionContext
sandbox -> Solari
```

`tools` and `sandbox` must not depend on Engine implementation details.

## Native deferred tool calling

Agents use Pydantic AI's native tool-calling/deferred-tool mechanism.

The model receives actual tool definitions rather than being asked to emit a custom `ToolCall` structured-output object.

Conceptually:

```text
LLM
  -> native tool call
  -> Pydantic AI deferred-tool handler
  -> Engine executor
  -> authorization/budget checks
  -> Tool
  -> SandboxManager
  -> tool result
  -> Pydantic AI/model
```

Do not reintroduce a custom "choose a ToolCall JSON object" protocol.

The Engine still has an outer match loop because it owns the lifetime of the match and runs Prisoner/Warden concurrently. Pydantic AI owns the model/tool interaction inside an agent run.

Do not build a second manual model/tool conversation loop around Pydantic AI.

## Match invariants

1. The Engine is authoritative.
2. Agents cannot directly mutate match state.
3. Agents cannot directly call Solari.
4. Tools cannot create or own `SandboxManager`.
5. Tools cannot deduct credits or enforce cooldowns.
6. Tool authorization is performed by the Engine.
7. Match completion is determined by the Engine.
8. Sandbox execution is performed by `SandboxManager`.
9. Prisoner and Warden have isolated scratchpads.
10. Hidden model reasoning is never captured or shared.
11. Host/API/database/model credentials never enter the sandbox.
12. Sandbox state is the game environment; host infrastructure is outside the game.

## Budgets and action pacing

Credits and cooldown/time pacing are **Engine concerns**.

Normal action tools consume the configured credit cost and participate in action cooldown/pacing.

The following tools are intentionally free and do not consume credits or action cooldown:

- `read_file`
- `write_file`
- `write_to_scratchpad`

This is deliberate: these are information/memory/workspace operations rather than costly game actions.

Do not move credit deduction or cooldown accounting into tools.

A zero-cost tool must not accidentally become a charged/cooldown action because it was invoked through the deferred-tool mechanism.

Match wall-clock timeout is owned by the Engine and is independent of individual tool credit cost.

## SandboxManager boundary

`SandboxManager` is the only Arbiter abstraction that directly executes sandbox operations.

Tools receive an `EngineExecutionContext`, which implements `ToolExecutionContext`. The context delegates to `SandboxManager`.

Do not add another `SandboxExecution` abstraction.

## V1 scope

Keep the current product intentionally narrow:

- deterministic developer-authored challenges
- fixed tool set
- one Solari sandbox per match
- Prisoner vs Warden
- read-secret as the primary challenge
- credits
- action cooldowns
- match timeout
- sandbox event monitoring
- server-authoritative result evaluation

Do not prematurely add user-created tools/challenges, distributed orchestration, sophisticated prompt-injection defenses, or a generic network-policy engine.

## Refactoring rules

When cleaning up the deferred-tool migration:

- remove obsolete structured-output tool selection code
- remove manual tool-call validation/coercion that only existed for model-produced `ToolCall` JSON
- remove prompt-based tool schema generation that duplicates native tool definitions
- remove manual observation plumbing whose only purpose was reconstructing tool-call conversations
- preserve scripted tool execution only if it is still useful for deterministic tests
- preserve the Engine authorization path
- preserve `SandboxManager` as the executor
- preserve zero-cost file/scratchpad semantics
- keep role-specific instructions and allowed-tool sets explicit

Before adding an abstraction, verify that Pydantic AI or the existing Engine already provides the required behavior.
