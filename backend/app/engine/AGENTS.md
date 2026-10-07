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

Setup settles three things, each for one reason:

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
- `chmod 700` on each agent's home, **appended last** so nothing after it can
  loosen one back up. `useradd -m` leaves the homes world-readable, which would
  let the Prisoner read the Warden's scratchpad — its plan — and the Warden the
  Prisoner's. The lockdown also follows the challenge's own `setup_script`,
  which runs before it.

Home isolation is one-directional in the strong sense, and this is the part to
be honest about. Mode 700 stops the Prisoner completely: it has no root, so no
route — `bash`, `read_file`, `write_file` — reaches the Warden's home. Against
the Warden it stops every *ordinary* route only. The Warden holds `NOPASSWD:ALL`
root and **root ignores file modes**, so a Warden that deliberately runs `sudo
cat /home/prisoner/scratchpad.txt` still reads it, and no file mode can change
that. Closing it would mean revoking the Warden's root, which the seeded
challenges need (the Warden's hint for *The Hidden Artifact* is that it can
disrupt the root-owned shards). So the Warden's instructions forbid it instead,
and `peek_prisoner_logs` is its one sanctioned window into the Prisoner's side.
`tests/test_privilege_boundaries.py` asserts both the wall and this residual, so
neither is assumed away.

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
reaches root by every one of them while the Prisoner reaches it by none. It also
covers the home lockdown: each side can still use its own home, neither can
list, read or write the other's through `bash` or `read_file`, and the Warden's
deliberate `sudo` read still succeeds (the residual above). It is opt-in
(`ARBITER_LIVE_SANDBOX=1`); run it after touching setup or privileges.

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

## Running out of credits

Credits are the Prisoner's budget for acting on the challenge. When the Prisoner
asks for a tool it cannot afford, the match **ends there** with the Warden as the
winner and `end_reason = PRISONER_OUT_OF_CREDITS` ("Prisoner out of usable
credits"), rather than the call being rejected and play continuing.

Waiting would reach the same Warden win by wall-clock timeout, having spent the
rest of the match watching an agent with nothing left to do. Ending at the
moment it is demonstrated says why.

Two things this rule deliberately does not do:

- **It does not touch free tools.** `can_afford` is `credits >= cost`, so a
  Prisoner on zero can still `read_file`, `write_file`, `write_to_scratchpad`
  and — importantly — `submit_flag`, which costs nothing. A Prisoner that has
  found the answer can still use it; the end only comes from reaching for
  something it cannot pay for.
- **It is not the Warden's rule.** A broke Warden is rejected and play
  continues. The sides are not symmetric: the Prisoner's credits are its budget
  for the objective, so being out is the end of its game. Do not "fix" the
  asymmetry without deciding what a Warden that cannot act is meant to mean.

It is also **skipped while replaying** (`_replay_mode`). The fork worker rebuilds
a sandbox through this same `execute_tool_call()` path, and finishing there
would stop the replay itself: every later call would come back
`match_not_running` and the snapshot would be rebuilt wrong.

### Both sides are told their balance

The Engine attaches the actor's remaining credits to **every** `ToolResult` it
returns, in `execute_tool_call()` via `_with_credit_balance()`, after the call
has run so a charged action reports what is left. Rejections carry it too —
`insufficient_credits`, `cooldown`, `tool_not_found` — because a refusal is
exactly when the number matters. The deferred executor hands the same result to
the model, so the balance lands in the model's tool-call conversation. Each
tool's price is on its model-facing description, generated from `ToolCost`
(`app/agents/AGENTS.md`).

The balance deliberately does **not** ride on the turn prompt. A match agent
issues tool call after tool call inside a single run; `_turn_prompt()` is
written once at the top of that run and never refreshed, so a number there is
stale from the first charge onward. The tool result is the one channel refreshed
per action. `run_turn()` takes no credits argument for that reason —
`_agent_loop()` no longer reads the balance and passes it.

That is what makes the rule above fair rather than arbitrary: the Prisoner can
see what it has and what things cost, so running out is a decision it made
badly, not arithmetic it was never shown. The Engine remains the only thing that
decides affordability — the number on the result is context, never authority.

The same balance is written into the persisted `tool_call` row's `result`, so
`GET /matches/events` reports the economy alongside each action. `_with_credit_balance()`
sets it, and nothing else may: a tool that could set its own balance could lie
about it.

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

`MAX_ACTIVE_TRAPS` (2) bounds how many traps the Warden may have armed and
unresolved at one time. Two covers a likely path and a backup without letting
the Warden blanket the sandbox; a slot is released when its trap fires, and the
Warden's instructions say to spend the two armings carefully.

State is a **list**, not a single slot, so a firing must resolve *the trap the
event matched* (`matching_trap()` then `trigger(state, trap)`) and leave the
others armed. Treating any event as "the trap fired" would silently disarm the
Warden's second trap -- and with it the coverage it was armed for.

Do not put trap semantics into sandbox monitoring or the Warden agent.

## Prisoner bash output cap

`PRISONER_BASH_OUTPUT_CHARS` (4000) bounds what one Prisoner `bash` call
returns, applied in `execute_tool_call()` alongside the credit and cooldown
rules -- not in the tool and not in `SandboxManager`.

Only the **head** is kept, so aiming a command at something larger reveals no
more than a small one. The result carries a truncation marker and a `notice`
saying how much was dropped, so the Prisoner never reasons from output it does
not know is incomplete. `stdout` and `stderr` are each capped; ``error`` is only
capped separately when it is not simply a copy of the stderr, so a failed
command's cut characters are counted once, not twice.

The Warden is deliberately exempt: its shell output is its own diagnostics for
the defence it is running, and this is a Prisoner-side balance rule, not a
shared transfer limit. The constant lives in the tool layer
(`agents/tools/shell.py`) only because the model-facing description quotes the
number; the Engine is what enforces it.

## stderr on a successful call

Every persisted `tool_call` row carries `stderr` from the sandbox, not just the
`error` summary. `SandboxManager` sets `success` from the command's exit code,
and a shell reports only its **last** line's status -- so a compound command
whose first line failed can still be green. `error` is deliberately `None` on a
zero exit (it is the failure reason, and code reads it that way), which means
stderr on its own field is the only record that the earlier line was refused.
The model reads it through the tool return and the archive reads it through
`GET /matches/events`.

Never "fix" this by flipping `success` to False whenever stderr is non-empty:
plenty of successful commands write warnings to stderr, and that would report
real work as failure.


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
