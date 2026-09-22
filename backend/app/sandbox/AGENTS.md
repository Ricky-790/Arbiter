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

The SDK client it caches owns an `httpx` connection pool tied to the event loop
it first ran on, and a Celery worker serves every match in its own
`asyncio.run()` loop. `SolariClient.client` therefore rebuilds the SDK client
whenever the running loop changes; never cache a loop-bound client in a plain
process-wide global, or the second match in a worker process dies with
`RuntimeError: Event loop is closed`.

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

Model-provided paths are used exactly as given: an absolute path stays
absolute, a relative path resolves against the acting user's working directory.
Only empty paths and NUL bytes are rejected. There is deliberately no workspace
scoping — the acting user's OS permissions are the access boundary, because file
operations run as that user rather than through a privileged API.

The scratchpad path is backend-controlled and actor-specific
(`/home/<user>/scratchpad.txt`) and never derived from model input.

The well-known Prisoner activity log at `/tmp/prisoner_logs` is written by the
Engine as root and left world-readable, so the Warden can read it while the
Prisoner cannot rewrite their own record.

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

Cleanup must happen even when agent tasks fail or timeout. `destroy_sandbox()`
tolerates a sandbox that was never created, so a setup failure is reported as
itself rather than replaced by a lookup error during cleanup.

## Concurrency

Avoid global mutable "current sandbox" state. Always use `match_id`.

Solari runs one live sandbox at a time. A match requested while another is
running therefore waits inside `get_or_create_sandbox()`, re-attempting until
the running match releases its slot (bounded by `SANDBOX_WAIT_SECONDS`), and
only then creates its own sandbox. Never give up after a fixed number of
attempts: a queued match must outlast the match that is holding the slot.

Per-match monitoring tasks, watchers, and cleanup state must be keyed by `match_id`.

## Network

Network restrictions are not a major V1 feature. The `block_network` capability exists as a Warden action, but do not build a general network-policy subsystem unless future challenges need it.

The fundamental assumption is that Solari isolates the sandbox from Arbiter infrastructure. Do not put Arbiter API/database/LLM credentials inside the sandbox.

## Do not

- import Engine/game rules into sandbox infrastructure
- decide match winners
- deduct credits
- enforce tool cooldowns
- expose host secrets
- bypass sandbox user permissions
