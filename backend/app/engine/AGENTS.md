# Engine — Agent Instructions

## Purpose

The Engine is the authoritative runtime for exactly one Arbiter match.

It owns:

- match state
- lifecycle
- action authorization
- credits
- cooldowns
- match timeout
- agent concurrency
- traps
- win/loss conditions
- sandbox setup/cleanup
- match-level events

If a rule determines whether an action is legal, what it costs, or whether the match ends, it belongs here.

## Native deferred-tool architecture

The Engine does **not** ask agents to produce a custom `ToolCall` structured output.

Agents use Pydantic AI native deferred tool calls.

The Engine binds an authoritative executor to each agent:

```text
Pydantic AI Agent
       |
       | native deferred request
       v
Engine executor
       |
       v
execute_tool_call()
       |
       +-- authorization
       +-- credits
       +-- cooldown
       +-- trap rules
       |
       v
EngineExecutionContext
       |
       v
Tool
       |
       v
SandboxManager
```

The Engine still owns an outer match loop that runs Prisoner and Warden concurrently and terminates the match on completion, failure policy, or timeout.

Do not recreate Pydantic AI's model/tool conversation loop in Engine.

## `execute_tool_call()`

This is the central authorization and budgeting boundary.

For a normal charged action:

```text
1. verify match is RUNNING
2. resolve tool
3. verify actor may use it
4. check action cooldown
5. check credits
6. validate Warden trap constraints when applicable
7. deduct credits
8. start action cooldown
9. create EngineExecutionContext
10. execute tool
11. record result
12. update trap state if applicable
```

### Free tools

These tools are intentionally exempt from credit deduction and action cooldown:

- `read_file`
- `write_file`
- `write_to_scratchpad`

For these tools:

```text
match running
 -> authorization
 -> execute
 -> result
```

Do not charge them or start the normal action cooldown.

The match's wall-clock timeout remains active independently.

## `EngineExecutionContext`

This is the per-action adapter between Engine and `ToolExecutionContext`.

It binds an actor to the Engine without exposing Engine internals to tools.

Tools must not receive:

- `match_id`
- `SandboxManager`
- mutable global actor state
- direct Engine state

The context derives the sandbox user from the challenge and delegates operations to `SandboxManager`.

## Sandbox execution

`SandboxManager` is the component that actually executes sandbox operations.

The Engine performs game-rule validation and then invokes tools through `EngineExecutionContext`.

The Engine must not make direct Solari calls.

Do not introduce `SandboxExecution` or another wrapper around `SandboxManager`.

## Agent concurrency

Prisoner and Warden run as independent asyncio tasks.

This is not strict turn-based execution.

The Engine controls:

- match wall-clock timeout
- action cooldown pacing
- credit budgets
- match termination

Each agent may be waiting on model inference while the other continues.

## Deferred-tool executor

The deferred-tool executor is an adapter, not a second agent runtime.

Its job is to:

1. receive a native Pydantic AI tool request
2. convert it into the Engine's internal tool request representation if needed
3. call `execute_tool_call()`
4. return the structured result to Pydantic AI

Do not duplicate authorization logic inside the deferred handler.

Do not manually build a model conversation or feed fake tool messages to the model.

## Match termination

`run_agents()` owns match-level orchestration.

It waits for:

- match completion
- Prisoner worker termination
- Warden worker termination
- optional match timeout

On timeout, the current V1 policy is Warden wins.

Always:

- cancel remaining agent tasks
- gather them
- save both agents' conversation histories (`_save_agent_messages`)
- destroy the sandbox
- leave the final match state authoritative

The saved histories are what a later fork can seed its agents from. They are
written best-effort, like the rest of the Engine's persistence: a storage
failure must not affect a match that has already finished.

## Fork restore

A fork rebuilds its sandbox from a parent match's persisted history before its
agents start. `run_agents(fork=...)` hands the Engine a `ForkPlan` -- produced
by `resumability.plan_fork()` -- carrying the Solari snapshot to boot from, if
any, and the calls still to replay on top of it.

`restore_sandbox()` runs `start()` (from the snapshot when there is one),
replays the remaining calls through the ordinary `execute_tool_call()` path with
`replay_at` set to each call's recorded timestamp, then snapshots the rebuilt
state for the next fork of that point.

While replaying, `_replay_mode` suppresses persistence, spectator emission, and
tracing, and `_replay_now` puts cooldown and trap-reaction comparisons on the
replayed clock rather than the wall clock. The prisoner activity log is
deliberately *not* suppressed: rebuilding it is part of restoring the sandbox.

Never replay a call through a second authorization path. The replay exists to
reproduce the live rules, so it must go through the real
`execute_tool_call()`.

## Win condition

For read-secret:

```text
submit_flag(correct_flag)
    -> Engine verifies ChallengeSpec.flag
    -> Prisoner wins
```

The LLM cannot declare itself the winner.

Future challenge success conditions must remain server-authoritative.

## Traps

`TrapManager` owns Warden trap state.

The sandbox layer observes actual events.

The Engine decides whether an event matches an armed trap and manages the Warden reaction window.

Do not put trap semantics into sandbox monitoring or the Warden agent.

## Scratchpad

The scratchpad is agent-owned persistent memory exposed as a normal voluntary tool.

The Engine may read the actor's scratchpad before an agent run to provide persistent context.

That read is backend context enrichment, not an agent action:

- no credits
- no cooldown
- no match action

Do not force a scratchpad write because a tool result is large.

## Refactoring rules

The deferred-tool migration should remove obsolete code such as:

- custom model-generated `ToolCall` output contracts
- manual argument coercion solely for repairing LLM JSON
- manual signature validation solely for model output
- prompt-based tool schema generation
- manual observation replay that duplicates Pydantic AI tool history
- custom "one tool call per output" protocols

Keep:

- Engine authorization
- credit/cooldown accounting
- match timeout
- trap validation
- server-authoritative result checking
- match event recording
- scripted execution support when useful for tests

## Observability

Logfire/Pydantic AI should capture normal agent/model/tool-call telemetry.

Engine-specific telemetry should record Arbiter concepts such as:

- match
- actor
- requested tool
- authorization result
- credits charged
- cooldown state
- execution result
- winner/reason

Telemetry must never become a game-rule dependency.
