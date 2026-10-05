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

### Tool-call timeout

Every tool call is bounded by `TOOL_TIMEOUT_SECONDS` (45s), applied in
`execute_tool_call()` -- not in a tool and not in `SandboxManager`, so it covers
every tool and both sandbox providers.

A call that outruns its budget is **abandoned, not failed or undone**: the
Engine returns a `ToolResult` with `failure_category: "timeout"` and a message
telling the agent what happened, that the match is still running, and that
whatever the command started may still be alive. The agent recovers on its next
turn and the match continues. Nothing about the timeout ends a match.

Why it exists, and why it is not optional:

- Neither provider bounds a command (E2B runs with `timeout=0`, Solari has no
  per-command timeout), so without this a command that never returns runs until
  the match wall clock -- and a timeout is **always a Warden win**, so stalling
  is an exploit, not just an accident.
- The action lock is **match-wide**. A hung call holds it, so the *opponent* is
  frozen too. Without a budget, one agent's bad command decides the match.
- A shell command can hang without meaning to: backgrounding a process with `&`
  but without redirecting its output leaves the child holding the stdout pipe
  open, so the runner never sees EOF and the call never completes.

The Prisoner's activity-log write runs through the sandbox inside the same lock,
so it is bounded too. It is best-effort: if the write times out the Engine logs
it and runs the call anyway.

Traps are unaffected and must stay that way. Arming `watch_file`,
`watch_process` or `auto_kill` returns immediately; the monitoring is a separate
task created by `SandboxManager`, outside the tool call, so no trap ever holds a
call open. Do not move trap monitoring inside the tool call or it becomes
subject to this budget.

The match wall-clock timeout is separate and unchanged. When it fires the Warden
still wins (`run_agents()`); the tool timeout exists so the match reaches a real
conclusion instead of waiting for that.

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

## Sandbox users and privileges

`_setup_commands()` creates the two sandbox users and settles their privileges
before either agent runs. It runs as root, so it is the **only** correct place
to change what either side may do — never do it by inspecting an agent's command
text.

It ends with two lines that exist for one reason each:

- `passwd -l root` — the images ship root with an **empty** password field, and
  PAM's `nullok` lets `su root` accept it. Without this line *both* agents can
  become root with no password, and every other permission in the sandbox —
  file modes, the prisoner/warden split, "the prisoner cannot kill the root
  supervisor" — is decorative.
- a `/etc/sudoers.d/arbiter-warden` drop-in granting the Warden
  `NOPASSWD:ALL` — what the Warden's instructions already promise. `usermod -aG
  sudo` alone does **not** grant it, because the created account has no password
  to authenticate with, so every `sudo` fails with "a password is required".
  `visudo -cf` validates the rule as part of setup, so a malformed file fails
  the match instead of silently breaking `sudo` for its duration.

Do not add command filtering to compensate. A regex over a shell command is not
a boundary: `s'u'do -n whoami` executes `sudo` and matches no `sudo` pattern,
and the same is true of `X=su; $X`, `$(printf su)do`, `env sudo`, a script the
agent writes and then runs, or a python one-liner. A denylist against shell
syntax fails *open*. Permission comes from the OS; the Engine only decides game
rules (credits, cooldowns, traps).

Never inject a password into an agent's command either. Tool arguments are
persisted to `match_events`, streamed to spectators and shown to the reviewer,
and an `echo pw | sudo -S` puts the secret in `argv` where the *other* agent can
read it with `ps`.

These rules cannot be checked offline — a mocked sandbox would agree with
whatever the test believed. `tests/test_privilege_boundaries.py` drives both
sides through the real `execute_tool_call()` path against a real sandbox, trying
ten different spellings of `sudo` and three of `su`, and asserting the Warden
reaches root by every one of them while the Prisoner reaches it by none. It is
opt-in (`ARBITER_LIVE_SANDBOX=1`); run it after touching setup or privileges.

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

Two separate processes and two separate plans, which is easy to conflate:

- The **fork worker** builds a fork. `plan_fork_build(match_id,
  branch_event_id)` returns a `ForkBuildPlan` naming the closest state already
  rebuilt (`base_snapshot_id`, or `None` for a bare template) plus the
  `tool_calls` still to replay. `fork_worker.build_snapshot()` then runs
  `start(from_snapshot=plan.base_snapshot_id)`, `begin_replay()`, replays each
  call, and `save_snapshot()`s the result, which the worker stores on the fork
  row along with both conversations.
- The **match worker** hosts a match started from a fork. The fork already
  reproduces the branch point, so `plan_resume(match_id)` returns a `ForkPlan`
  carrying just the snapshot to boot and each agent's conversation.
  `run_agents(fork=...)` boots it and seeds the histories; it never replays.

Replay goes through the ordinary `execute_tool_call()` path with `replay_at` set
to each call's recorded timestamp. While replaying, `_replay_mode` suppresses
persistence, spectator emission, and tracing, and `_replay_now` puts cooldown
and trap-reaction comparisons on the replayed clock rather than the wall clock.
The prisoner activity log is deliberately *not* suppressed: rebuilding it is
part of restoring the sandbox.

Never replay a call through a second authorization path. The replay exists to
reproduce the live rules, so it must go through the real `execute_tool_call()`.

### Setup is skipped when a snapshot is booted

`start()` runs `_setup_commands()` **only** when `from_snapshot is None`. A
snapshot already contains the challenge setup, so a fork boots it and replays
only the calls on top; it never re-runs setup.

The consequence to remember: every snapshot chain has exactly one root that ran
setup — the first fork of a root match has no `base_snapshot_id`, so it *does*
set the challenge up, and every fork and restore built from it inherits that
state. So a change to `_setup_commands()` reaches new root matches and new fork
chains, never an existing snapshot. That applies to everything setup does —
users, privileges, challenge files, and the `setup_script`'s services — so a
challenge edited after a snapshot exists will still be served in its old form to
forks built from that snapshot.

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
