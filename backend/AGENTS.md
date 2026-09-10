# Arbiter Backend — Agent Instructions

## Purpose

This directory contains the Python backend for **Arbiter**, an AI-vs-AI adversarial sandbox platform. Two LLM-controlled agents compete inside an isolated Solari sandbox:

- **Prisoner**: attempts to achieve the challenge objective, currently the `read-secret` challenge.
- **Warden**: attempts to prevent the Prisoner from succeeding.

The backend currently focuses on the core match runtime. API, persistence, frontend integration, and production orchestration are intentionally still minimal.

## Current stack

- Python >= 3.12
- FastAPI
- Pydantic / Pydantic AI
- Solari Sandbox
- Rich logging
- `uv` for dependency/environment management

The dependency set is defined in `pyproject.toml`. Do not introduce a new framework or infrastructure component unless it solves a concrete problem.

## Architecture

The main runtime is split into three domains:

```text
agents/
    LLM decision-making
    tool declarations and execution contracts

sandbox/
    Solari integration
    sandbox lifecycle
    filesystem/process/network operations
    sandbox event monitoring

engine/
    match state
    timing
    credits
    cooldowns
    trap rules
    action authorization
    win/loss conditions
```

Dependency direction:

```text
engine -> agents/tools
engine -> sandbox

agents/tools -> ToolExecutionContext
sandbox -> Solari

sandbox must not depend on engine
tools must not depend on engine
```

The Engine is the game authority. Agents request actions; the Engine validates and executes them.

## Match model

A match has exactly one `Engine` instance and one sandbox identified by `match_id`.

The Engine concurrently runs two agent loops:

```text
Prisoner agent loop ──┐
                      ├── Engine ── Solari sandbox
Warden agent loop ────┘
```

This is asynchronous concurrency, not strict turn-taking. LLM latency and cooldowns can cause either agent to act more frequently.

The Engine owns:

- match lifecycle
- timeout handling
- action validation
- tool availability
- cooldowns
- credits
- Warden traps
- sandbox events relevant to game rules
- objective completion
- winner/reason
- cleanup

## Core invariants

1. **The Engine is authoritative.** Agents cannot directly mutate match state.
2. **Tools are capabilities, not game rules.** A tool delegates through `ToolExecutionContext`.
3. **Agents do not receive private opponent reasoning.**
4. **Sandbox state is observable only through legitimate sandbox/tool mechanisms.**
5. **Do not put match state into global mutable state.**
6. **Never expose Arbiter host credentials or secrets to a sandbox.**
7. Sandbox compromise is part of the game; host/infrastructure compromise is not.
8. V1 does not need generic LLM safety filtering, prompt-injection detection, or a sophisticated network-policy framework.

## Tool execution flow

```text
LLM
  -> ToolCall
  -> Engine.execute_tool_call()
  -> authorization / cooldown / credits / trap validation
  -> EngineExecutionContext
  -> Tool
  -> SandboxManager
  -> SolariClient
  -> Solari
```

Do not bypass this path from an agent.

## Observability

The intended observability boundary is `app/observability/`.

The Engine should eventually emit structured match events and observations without becoming coupled to Langfuse directly. Observability should be a side-effect of execution, not part of the game rules.

Useful events include:

- match started/finished
- LLM request started/completed/failed
- tool requested/started/completed/failed
- sandbox event
- trap triggered
- agent/provider error

Never log API keys, BYOK credentials, or other secrets.

## V1 scope

The current product is intentionally narrow:

- deterministic developer-authored challenges
- fixed tool set
- one sandbox per match
- Prisoner vs Warden
- `read-secret` as the primary challenge
- match timeout
- credits and cooldowns
- sandbox event monitoring
- model/provider calls through Pydantic AI

Do not prematurely build user-created challenges, user-created tools, elaborate policy engines, or distributed infrastructure.

## Development workflow

Run commands from `backend/`.

Prefer:

```bash
uv sync
uv run python main.py
```

Use the project's existing dependency versions and Python version.

Before changing architecture, inspect the relevant domain's `AGENTS.md`.

When modifying behavior:

1. Understand which domain owns the behavior.
2. Keep dependencies flowing in the documented direction.
3. Preserve server-authoritative match rules.
4. Add/update tests where practical.
5. Avoid unrelated refactors.

## Important anti-patterns

Avoid:

- putting game logic inside tools
- letting tools instantiate `SandboxManager`
- letting tools know `match_id`
- adding a second abstraction around `SandboxManager` merely to wrap Solari
- storing a mutable "current sandbox"
- sharing agent observations between Prisoner and Warden
- trusting an LLM's claimed result instead of checking actual sandbox state
- treating logging as the source of truth for match results

## Security boundary

The key V1 security assumption is that Solari isolates the sandbox from Arbiter infrastructure. Validate this assumption operationally, but do not build a large network-security subsystem unless future challenges require it.

The most important boundaries are:

- no host secrets in sandbox
- resource/time limits
- sandbox isolation
- server-authoritative results
- Engine-side tool authorization
- output limits
