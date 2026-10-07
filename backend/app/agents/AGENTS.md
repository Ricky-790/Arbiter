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

## Models: always BYOK

`agents_directory.py` owns the catalogue, and `resolve_model()` is the only
entry point the agent runtime uses.

`PROVIDERS` maps a provider name onto the pydantic-ai provider/model classes
that serve it, and `PROVIDER_MODELS` lists *suggested* models per provider. The
picker chooses a provider and a model separately; the two are stored separately
on the `matches` row and joined into the canonical `provider:model` that
`resolve_model()` resolves.

**`PROVIDER_MODELS` is not a whitelist.** An operator may paste any model name
under a known provider, so `join_model_name()` only checks the provider and that
the model is non-blank. Whether a name is real is decided by
`check_model_exists()`, which reads the provider's own model list using the
caller's key and raises `ModelCheckError` with a reason of `not_found`,
`key_rejected` or `unreachable`. The curated names exist only so the picker is
not empty: only OpenRouter publishes a keyless list.

This check is not cosmetic. The worker claims a sandbox before the first model
call, so a name that only failed at generation time would occupy a scarce
sandbox and produce nothing. `POST /matches/verify-model` answers the UI while
the operator types, and both start routes verify again before queueing (fail
closed, including when the provider cannot be reached).

**Every model is BYOK.** Arbiter holds no provider credentials for agent models:
there is no free tier and no `agent_mapper`. `build_model()` takes the caller's
API key as an argument, and `resolve_model()` rejects a missing key rather than
falling back to anything.

Never read a provider key from the environment and never assign one to one. Keys
arrive per match from the request body, travel to the worker through the
encrypted store in `app/secrets`, and are passed to `ToolChoosingAgent(api_key=)`.
A provider's own error text is never surfaced to the caller, because it can echo
the request URL and some SDKs put the key there; the cache is keyed by a digest
so no key is retained.

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

### Message history must stay resumable

A stored history must never end on a model response whose tool calls have no
results. pydantic-ai refuses to start a run from one
(`Cannot provide a new user prompt when the message history contains unprocessed
tool calls`), and because the Engine's turn loop retries after a failed turn, the
agent would fail identically on *every* later turn until the match timed out.

The deferred-tool handler is the dangerous place: it runs *before* the results it
returns exist, so pydantic-ai's view at that moment ends on exactly that shape.
Anything snapshotting the conversation there must trim the incomplete tail
(`_drop_pending_tool_calls`). `run_turn` also repairs the history before each
run, so a damaged history costs one unfinished response rather than the match.

Dropping that tail loses only the in-flight response. The tool calls it carried
are still recorded as match events, which is what a fork replays from.

## Tool definitions

Tool schemas should be native Pydantic AI tool definitions derived from the registered tools.

Do not maintain a second prompt-only tool description format.

`BaseTool.description` and the typed `execute()` signature are the source metadata used to construct the model-facing tool definition.

The model should not receive internal fields such as:

- `match_id`
- sandbox user identity
- Engine state
- internal execution context

The one deliberate exception is the **credit balance**, which is game
information rather than an internal field: it decides what an agent can do, and
for the Prisoner a misjudged spend is fatal. It reaches the model two ways, and
they only work as a pair:

- `ToolResult.credits` carries the balance the Engine attached to the result the
  agent just read. It is on *every* result, executed or rejected, because the
  agent spends almost a whole turn issuing tool call after tool call inside one
  run — a prompt is written once at the top of that run and never refreshed, so
  a balance carried there would be stale from the first charge onward. It is
  Engine-owned data on the result, not something a tool sets, and it is `None`
  only for the reviewer, which has no economy.
- `_build_tool_definitions()` appends `Costs N credits.` to every tool that has
  a `ToolCost`. It is derived from the cost rather than written into each
  description, so what the model is told and what the Engine charges cannot
  drift. Tools with no `cost` attribute at all — the reviewer's — get no line.

A balance with no prices is not actionable, and prices with no balance are not
either. Do not add one without the other, and never hard-code a price into a
tool description while the note is generated from `BaseTool.cost`.

Do not put the balance back in `_turn_prompt()`. It is context, not authority —
the Engine still decides what is affordable — and the prompt is the wrong
channel for a number that changes between two tool calls within one run.

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

Retries are bounded per turn (429/503/504). When the budget is exhausted the
agent raises `AgentUnavailableError` immediately: never sleep on the final
failure, because nothing can recover and the wait only delays the Engine
stopping the match. `Retry-After` is honoured for rate limits but clamped
(`_max_retry_wait_seconds`) so a large value cannot consume the match's
wall-clock budget. Only attempts that actually retry are reported as
`agent_retry`; the last one reaches the match log as `agent_unavailable`.

The Strategy Reviewer is the one agent that overrides this timing. A match
agent's cooldown is spent against a match wall clock, which is exactly what a
review does not have: its caller is watching a stream, so a provider hiccup is
worth riding out rather than failing the run. `StrategyReviewerAgent` replaces
`_retry_wait` with a flat `_review_retry_wait_seconds` (45s) for every retryable
status, ignoring `Retry-After` — waiting longer than a provider asks is safe,
and a short `Retry-After` would only retry back into the same limit and spend
one of the three attempts. Do not move this into the base class: 45s is wrong
for a match, whose remaining wall clock the wait comes out of.

## Prisoner and Warden

`prisoner/` and `warden/` should remain thin role-specific wrappers.

They configure:

- role instructions
- model
- objective
- allowed tools
- optional scripted calls for tests

Do not duplicate the agent runtime in these packages.

## The Strategy Reviewer

`strategy_reviewer/` is the one agent here that does **not** play a match. It
reads a finished one and writes a better strategy for one side.

It is still a `ToolChoosingAgent`, so it inherits the same deferred-tool
machinery, history repair and provider retry handling. What differs:

- **A different toolset.** Its tools come from `agents/tools/review_tools/`, not
  `build_default_registry()`. Those read through `app.reviewer`, and a review
  registry exposes nothing that acts inside a sandbox. Never give this agent a
  match tool.
- **A bound match, not a chosen one.** The match id lives on the
  `ReviewContext` handed to every tool; it is never a tool argument. The model
  chooses which question to ask, never which match to ask about.
- **Its own prompt.** `_turn_prompt()` is overridden, so it gets the challenge
  framing and the strategy under review instead of a match objective and
  scratchpad.
- **A request limit.** `_request_limit` bounds its model requests. A match agent
  is paced by the Engine's turn loop and the match clock; a one-shot agent has
  nothing else bounding it, so it must set this.
- **Its own retry cooldown.** `_retry_wait` is overridden to a flat 45s for
  429/503/504, rather than the base 30s-or-`Retry-After`. See "Provider errors"
  above for why the timing differs.

It is read-only in the strong sense: no Engine, no sandbox, no `SandboxManager`,
and nothing it reads can be changed. Its output is a proposal, returned and
never saved -- promoting it is a separate, deliberate
`POST /strategies/save-strategy`.

Do not let it become a match participant. A capability that would let it act in
a match does not belong in `review_tools/`.

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
