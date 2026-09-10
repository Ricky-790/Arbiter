# Sandbox — Agent Instructions

## Purpose

This package is Arbiter's infrastructure adapter around Solari.

It owns:

- Solari client interaction
- sandbox creation/destruction
- match_id -> sandbox mapping
- command execution
- file operations
- process/file monitoring
- sandbox events
- challenge setup primitives

It must not own match rules.

## Components

### `client.py`

`SolariClient` is the thin adapter around the Solari SDK/API.

Keep it focused on translating Arbiter calls to Solari operations. Do not put Arbiter match rules here.

### `manager.py`

`SandboxManager` is the Arbiter-specific sandbox abstraction.

It maintains per-process registries keyed by `match_id` and exposes operations used by tools/Engine.

Do not add another generic `SandboxExecution` layer. `SandboxManager` already provides the necessary Arbiter abstraction over `SolariClient`.

A single `SandboxManager` can be shared by multiple Engine instances in one worker process. It is not a distributed singleton.

### `monitor.py`

Handles sandbox monitoring and converts observed sandbox changes into callbacks/events.

### `models.py`

Contains sandbox infrastructure and challenge configuration models such as:

- `SandboxConfig`
- `CommandResult`
- `SandboxEvent`
- `ChallengeSpec`

## Isolation

Sandbox operations must execute as the intended sandbox user whenever user permissions matter.

For example, file reads are intentionally performed through shell execution as the acting user instead of using privileged file APIs that would bypass OS permissions.

## Filesystem

Agent workspace paths are validated and scoped by user.

The scratchpad path is backend-controlled and actor-specific.

Do not let model-provided paths escape the intended workspace when using `write_file`.

## Lifecycle

Typical lifecycle:

```text
Engine.start()
    -> SandboxManager.get_or_create_sandbox()
    -> register event handler
    -> deterministic challenge setup

match runs

Engine.finally
    -> SandboxManager.destroy_sandbox()
```

Cleanup must happen even when agent tasks fail or timeout.

## Network

Network restrictions are not a major V1 feature. The `block_network` capability exists as a Warden action, but do not build a general network-policy subsystem unless future challenges need it.

The fundamental assumption is that Solari isolates the sandbox from Arbiter infrastructure. Do not put Arbiter API/database/LLM credentials inside the sandbox.

## Concurrency

Avoid global mutable "current sandbox" state. Always use `match_id`.

Per-match monitoring tasks, watchers, and cleanup state must be keyed by `match_id`.

## Do not

- import Engine/game rules into sandbox infrastructure
- decide match winners
- deduct credits
- enforce tool cooldowns
- expose host secrets
- bypass sandbox user permissions
