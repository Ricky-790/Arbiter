# Engine — Agent Instructions

## Purpose

The Engine is the authoritative runtime for one Arbiter match.

It owns:

- match state
- lifecycle
- action validation
- cooldowns
- credits
- traps
- timing
- agent concurrency
- win/loss conditions
- sandbox setup/cleanup

If a rule determines whether an action is legal or whether the match has ended, it belongs here.

## `Engine`

Each Engine represents exactly one active match.

Constructor inputs include:

- `match_id`
- `ChallengeSpec`
- `SandboxManager`
- optional `ToolRegistry`
- cooldown configuration

The Engine creates the sandbox through `SandboxManager`.

## Action execution

`execute_tool_call()` is the central authorization boundary.

Current sequence:

```text
1. verify match is RUNNING
2. resolve tool
3. verify actor can use tool
4. check cooldown
5. check credits
6. validate Warden trap constraints
7. deduct credits
8. start cooldown
9. create EngineExecutionContext
10. execute tool
11. record result
12. update trap state if applicable
```

Do not move these checks into individual tools.

## `EngineExecutionContext`

This is the per-action adapter between Engine and `ToolExecutionContext`.

It binds an actor to an Engine so tools do not need:

- `match_id`
- user identity
- SandboxManager
- Engine internals

It derives the acting sandbox user from the challenge.

Do not replace this with mutable "current actor" global state.

## Concurrency

Prisoner and Warden run as independent asyncio tasks.

The Engine is not turn-based.

The `_action_lock` currently serializes critical match actions. Be careful when changing it: holding the lock across slow sandbox/tool operations can limit concurrency. If this is optimized later, preserve atomicity around state validation/updates.

## Match termination

Normal termination uses `_stop_event`.

`run_agents()` waits for:

- match stop
- Prisoner worker completion
- Warden worker completion
- optional timeout

On timeout, Warden currently wins.

Always cancel and gather worker/waiter tasks and destroy the sandbox in cleanup.

## Traps

`TrapManager` owns Warden trap state.

The sandbox layer observes actual events; the Engine decides whether an event matches a trap and opens the Warden reaction window.

Do not move trap semantics into the sandbox monitor.

## Win condition

For the current read-secret challenge, `submit_flag` is checked against `ChallengeSpec.flag` by the Engine.

The LLM cannot declare itself the winner.

Future challenge-specific success conditions should remain server-authoritative.

## Events and observability

The Engine currently records lightweight events in match state via `_record()`.

The planned `app/observability` package should eventually receive structured events/LLM/tool telemetry without making Langfuse a game-rule dependency.

Prefer a clean event boundary such as:

```text
Engine
  -> structured match event
      -> logger
      -> observability
      -> future WebSocket
      -> future DB
```

## Errors and provider retries

Provider failures should be handled at the agent/provider boundary with bounded retry behavior where appropriate.

A single agent's provider failure should not automatically freeze the opponent or stop the match unless the defined match policy says so.

Unexpected agent-loop termination should end the match rather than silently leaving the other worker alive.

## Avoid

- game logic inside tools
- direct Solari calls from Engine
- global match state
- trusting model output as proof of success
- coupling Engine to HTTP/database/frontend concerns
