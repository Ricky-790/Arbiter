# AGENTS.md

## Arbiter Backend — AI-vs-AI Sandbox Contest Platform

This document describes the architecture, responsibilities, invariants, and development conventions for the Arbiter backend.

Arbiter is an adversarial AI sandbox platform where two AI agents compete inside an isolated virtual machine:

* **Prisoner** — attempts to accomplish a challenge objective, typically by escaping restrictions or accessing a protected resource.
* **Warden** — attempts to detect, prevent, or respond to the Prisoner's actions.
* **Sandbox** — an isolated Solari microVM in which the match takes place.
* **Engine** — owns the state and rules of one active match.
* **SandboxManager** — manages sandbox instances and provides the interface between the game and Solari.

The backend should be designed so that multiple matches can run concurrently while remaining completely isolated from one another.

---

# 1. Core Architecture

The backend is divided into three major domains:

```text
agents/
    AI decision-making and tools

sandbox/
    Solari sandbox infrastructure

engine/
    Match runtime and game rules
```

The dependency direction is:

```text
                 ┌───────────────┐
                 │    Engine     │
                 └───────┬───────┘
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
        ┌───────────┐         ┌───────────┐
        │   Agents  │         │  Sandbox  │
        └─────┬─────┘         └─────┬─────┘
              │                     │
              ▼                     ▼
        Agent Tools              Solari
```

The important separation is:

> Agents decide what they want to do.
> Tools define what actions are available.
> Sandbox executes those actions in the VM.
> Engine decides whether and when those actions are allowed and how they affect the match.

Do not move game rules into the sandbox layer.

Do not put Solari-specific implementation details into the engine.

---

# 2. Backend Directory Structure

The intended backend structure is:

```text
backend/
├── app/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── base.py
│   │   ├── prisoner.py
│   │   ├── warden.py
│   │   ├── prompts.py
│   │   │
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── models.py
│   │       ├── base.py
│   │       ├── registry.py
│   │       ├── execution.py
│   │       ├── filesystem.py
│   │       ├── shell.py
│   │       ├── process.py
│   │       ├── network.py
│   │       └── system.py
│   │
│   ├── sandbox/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── client.py
│   │   ├── manager.py
│   │   └── monitor.py
│   │
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── engine.py
│   │   ├── state.py
│   │   ├── events.py
│   │   ├── event_bus.py
│   │   ├── scheduler.py
│   │   ├── credits.py
│   │   ├── cooldowns.py
│   │   ├── traps.py
│   │   ├── reactions.py
│   │   ├── rules.py
│   │   └── win_conditions.py
│   │
│   └── main.py
│
└── AGENTS.md
```

Some files may be introduced later as the implementation grows. Do not create abstractions simply to match this structure if they are not currently needed.

---

# 3. Match Lifecycle

A match follows this high-level lifecycle:

```text
Match Created
     │
     ▼
Challenge Loaded
     │
     ▼
Sandbox Created
     │
     ▼
Sandbox Environment Setup
     │
     ▼
Prisoner + Warden Initialized
     │
     ▼
Match Started
     │
     ▼
┌───────────────────────────────────┐
│          Match Runtime            │
│                                   │
│  Prisoner ──┐                     │
│             ├── Scheduler         │
│  Warden ────┘                     │
│                                   │
│  Tool calls → Sandbox             │
│  Sandbox events → Monitor         │
│  Events → Rules / Traps / Engine  │
│                                   │
└───────────────────────────────────┘
     │
     ├── Prisoner achieves objective
     │
     ├── Warden prevents objective
     │
     ├── Prisoner runs out of credits
     │
     ├── Match timeout
     │
     └── Error
     │
     ▼
Match Finished
     │
     ▼
Sandbox Destroyed
```

For the first implementation, the entire lifecycle should run in one process.

Do not introduce the API, database, frontend, or distributed workers until the core match lifecycle works reliably.

---

# 4. Engine Is Per-Match

`Engine` represents the runtime of **one match**.

There should be one engine instance per active match:

```python
engine = Engine(
    match_id=match_id,
    ...
)

await engine.run()
```

For three concurrent matches:

```text
Engine A → Match A
Engine B → Match B
Engine C → Match C
```

Each engine owns its own:

* MatchState
* Prisoner agent
* Warden agent
* scheduler state
* cooldown state
* trap state
* reaction windows
* event handling relevant to that match

No match-specific state should be stored globally.

---

# 5. SandboxManager Is Shared Infrastructure

`SandboxManager` is different from `Engine`.

The intended design is:

```text
SandboxManager
    │
    ├── match-A → Sandbox A
    ├── match-B → Sandbox B
    └── match-C → Sandbox C
```

It maintains an in-memory registry:

```python
self.sandboxes: dict[str, Sandbox]
```

where the key is the `match_id`.

Conceptually:

```python
sandbox = await sandbox_manager.get_sandbox(match_id)
```

The manager either returns the existing sandbox or creates it.

The manager is responsible for:

* creating sandboxes
* tracking active sandboxes
* executing sandbox operations
* setting up environments
* destroying sandboxes
* translating Arbiter operations into Solari operations

It should not contain match rules.

For example, `SandboxManager` should not decide:

```text
"Prisoner has no credits, therefore Warden wins."
```

That belongs to the engine.

---

# 6. SolariClient

`SolariClient` is a thin adapter around the Solari SDK.

Its job is to hide direct Solari API interaction from the rest of Arbiter.

Typical responsibilities:

```python
class SolariClient:
    async def create_sandbox(...)
    async def destroy_sandbox(...)
```

Potentially later:

```python
async def connect(...)
async def create_from_snapshot(...)
```

Do not put Arbiter-specific game logic here.

For example, this belongs in `SolariClient`:

```python
await self.client.create(...)
```

This does not:

```python
if prisoner_credits <= 0:
    ...
```

---

# 7. SandboxManager

`SandboxManager` is the primary sandbox abstraction exposed to the engine and tools.

A conceptual interface is:

```python
class SandboxManager:

    async def get_sandbox(
        self,
        match_id: str,
    ) -> Sandbox:
        ...

    async def run_command(
        self,
        match_id: str,
        command: str,
        user: str,
    ) -> CommandResult:
        ...

    async def read_file(
        self,
        match_id: str,
        path: str,
        user: str,
    ) -> str:
        ...

    async def write_file(
        self,
        match_id: str,
        path: str,
        content: str,
        user: str,
    ) -> None:
        ...

    async def setup_environment(
        self,
        match_id: str,
        challenge: ChallengeSpec,
    ) -> None:
        ...

    async def destroy_sandbox(
        self,
        match_id: str,
    ) -> None:
        ...
```

The exact methods may change as implementation progresses.

Prefer exposing meaningful sandbox operations instead of allowing the engine to directly manipulate the Solari object.

---

# 8. Sandbox Models

`app/sandbox/models.py` contains Pydantic schemas belonging to the sandbox domain.

Important models include:

## SandboxConfig

Describes the resources/configuration of a sandbox.

```python
class SandboxConfig(BaseModel):
    template: str = "base"
    cpu: int = 2
    mem_mb: int = 4096
```

## CommandResult

Represents command execution results:

```python
class CommandResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
```

## SandboxEvent

Represents an observable event originating from the sandbox.

Events may include:

* file creation
* file modification
* file deletion
* process start
* process exit
* network activity
* command execution

Sandbox events should contain enough structured information for the engine and trap system to evaluate them.

---

# 9. ChallengeSpec

`ChallengeSpec` describes the environment and objective of a challenge.

It belongs to the sandbox domain for now because it primarily describes how the environment should be constructed.

Example:

```python
ChallengeSpec(
    name="Protected File",
    description="Access a protected file containing the flag.",
    win_condition="prisoner_submits_flag",
    flag="ARB{example}",
    files={
        "/root/secret.txt": "ARB{example}",
    },
)
```

The important design principle is:

> Challenge configuration should describe the desired environment, not contain arbitrary root shell code.

Avoid designs where an LLM directly generates and executes arbitrary setup scripts as root.

Prefer:

```text
ChallengeSpec
      ↓
SandboxManager
      ↓
deterministic setup operations
      ↓
Solari Sandbox
```

Dynamic challenge generation may be added later, but generated specifications must be validated before they are applied.

---

# 10. Sandbox Setup

For the initial version, sandbox setup should be deterministic.

The setup process may include:

```text
Create users
    ↓
Create directories
    ↓
Create files
    ↓
Set ownership
    ↓
Set permissions
    ↓
Configure challenge-specific vulnerabilities
    ↓
Start monitoring
```

The setup code must run with the appropriate privileges inside the sandbox.

Do not rely on the Prisoner or Warden agent to construct the initial challenge environment.

---

# 11. Sandbox Monitoring

`SandboxMonitor` observes activity occurring inside the sandbox.

Its job is observation, not game-rule enforcement.

Conceptually:

```text
Solari Sandbox
      │
      ▼
SandboxMonitor
      │
      ▼
SandboxEvent
      │
      ▼
Engine EventBus
```

Solari provides filesystem watching capabilities through its SDK.

However, not every event needed by Arbiter can necessarily be obtained directly from Solari's filesystem watcher.

For example:

```text
File modification     → filesystem watcher
File access/read       → guest instrumentation may be required
Process execution      → process/audit instrumentation
Network activity       → guest/network instrumentation
```

The monitor should normalize these sources into `SandboxEvent` objects.

The rest of Arbiter should not need to know whether an event came from Solari's API, auditd, inotify, or another mechanism.

---

# 12. Agents

Agents are responsible for deciding what action they want to take.

There are two primary agents:

```text
PrisonerAgent
WardenAgent
```

Agents should not directly manipulate the game state.

For example, an agent should not directly do:

```python
state.credits -= 2
```

Instead, it requests an action:

```text
Agent
  ↓
Tool call
  ↓
Engine validates/schedules
  ↓
Tool executes
  ↓
Result returned
  ↓
Engine updates state
```

This keeps the LLM from becoming an authority over game state.

---

# 13. Agent Output

Agent output should be structured.

Do not depend on parsing arbitrary natural-language responses such as:

```text
"I think I should run ls first..."
```

Prefer a structured action:

```python
GameAction(
    actor=AgentType.PRISONER,
    action_type=ActionType.BASH,
    params={
        "command": "ls -la /tmp"
    },
)
```

PydanticAI should use structured output where possible.

The agent may produce a concise reasoning summary for observability, but private chain-of-thought must not be exposed or streamed.

---

# 14. Tools

Tools live under:

```text
app/agents/tools/
```

Tools represent capabilities available to agents.

Examples:

```text
Prisoner:
    bash
    read_file
    write_file
    list_dir
    python
    submit_flag

Warden:
    bash
    read_file
    list_dir
    list_processes
    kill_process
    watch_file
    watch_process
    auto_kill
    block_network
```

Tool definitions should contain:

* name
* description
* input schema
* cost
* allowed agent type
* execution implementation

---

# 15. Tool Registry

`ToolRegistry` is responsible for registering and exposing tools.

It should support operations conceptually similar to:

```python
register(tool)
get(name)
get_for_agent(agent_type)
schemas_for_agent(agent_type)
```

The registry should ensure that an agent cannot request a tool it is not allowed to use.

For example:

```text
Prisoner → kill_process
```

must not be executable merely because the LLM requested it.

The registry and engine should enforce authorization.

Never rely only on the LLM prompt to enforce permissions.

---

# 16. Tool Execution

Tool execution should follow this flow:

```text
Agent chooses tool
        ↓
Engine receives action
        ↓
Validate action
        ↓
Check agent permissions
        ↓
Check credits
        ↓
Check cooldown
        ↓
Execute tool
        ↓
Sandbox operation
        ↓
ToolResult
        ↓
Update match state
        ↓
Emit events
```

The engine is the authority for whether an action can happen.

---

# 17. Credits

Credits are a strategic game mechanic.

Every tool has a cost.

Example:

```text
bash             2
read_file        1
write_file       2
list_dir         1
python           3
list_processes   2
kill_process     5
watch_file       3
watch_process    4
auto_kill       15
block_network    8
submit_flag      0
pass             0
```

Credits should be managed by a dedicated engine component.

Agents must not modify their own credits.

The engine should:

1. Check available credits.
2. Reserve/deduct the tool cost.
3. Execute the tool.
4. Record the result.
5. Emit a credit-change event.

Credits should be represented in match state.

---

# 18. Cooldowns

Credits and cooldowns are separate mechanics.

Credits determine:

> "Can I afford this action?"

Cooldowns determine:

> "Can I perform this action again yet?"

For example:

```text
bash
    cost: 2 credits
    cooldown: 5 seconds

list_dir
    cost: 1 credit
    cooldown: 2 seconds
```

A cooldown should apply to the agent/tool that used it.

A Prisoner's cooldown must not freeze the entire match.

The Warden should continue operating while the Prisoner is on cooldown, and vice versa.

---

# 19. Match Scheduling

The game should not use a strict:

```text
Prisoner
   ↓
Warden
   ↓
Prisoner
   ↓
Warden
```

turn model.

Instead, both agents operate independently.

Conceptually:

```text
              Match
                │
          ┌─────┴─────┐
          ▼           ▼
      Prisoner      Warden
       loop           loop
          │           │
       cooldown    cooldown
          │           │
          └─────┬─────┘
                ▼
            Event Bus
```

The scheduler determines when each agent may act.

Each agent can have:

```text
next_action_at
```

or equivalent cooldown state.

The global match timeout applies to the entire match.

---

# 20. EventBus

The EventBus is the communication mechanism between match components.

Use a canonical `MatchEvent` model.

Potential event types:

```text
MATCH_STARTED
MATCH_ENDED

AGENT_ACTION_REQUESTED
TOOL_CALL
TOOL_RESULT

COOLDOWN_STARTED
COOLDOWN_ENDED

CREDITS_CHANGED

SANDBOX_EVENT

TRAP_ARMED
TRAP_TRIGGERED

REACTION_STARTED
REACTION_ENDED

FLAG_SUBMITTED
```

The exact event list may evolve.

The EventBus should eventually allow the same events to be consumed by:

```text
Engine rules
Trap system
Logging
Persistence
WebSocket streaming
Analytics
```

This avoids coupling the core engine directly to the frontend.

---

# 21. Traps

Traps are Warden capabilities that react to sandbox activity.

Examples:

```text
watch_file
watch_process
auto_kill
block_network
```

A trap should be represented as state rather than simply being inferred from the Warden's previous action.

Conceptually:

```text
Warden
  │
  │ arm trap
  ▼
TrapManager
  │
  ▼
SandboxMonitor
  │
  │ matching SandboxEvent
  ▼
Trap triggered
  │
  ▼
MatchEvent
```

Do not rely exclusively on post-hoc checks such as:

```python
if "secret.txt" in action.params["path"]:
    ...
```

when a real sandbox event can be observed.

---

# 22. Trap Triggering

When a trap matches a sandbox event:

```text
SandboxEvent
     ↓
TrapManager
     ↓
Matching trap?
     │
    yes
     ↓
TRAP_TRIGGERED
     ↓
Reaction window
```

Trap firing should not automatically freeze the Prisoner.

Instead, a triggered trap creates a Warden reaction opportunity.

---

# 23. Reaction Windows

A trap trigger should open a short Warden reaction window.

Initial recommended behavior:

```text
Trap triggered
      ↓
~10 second reaction window
      ↓
Warden gets priority/opportunity to respond
      ↓
Reaction window ends
      ↓
Normal match scheduling continues
```

The exact duration should eventually be configurable.

The reaction window should not stop the sandbox or globally pause time.

---

# 24. Win Conditions

Win-condition evaluation belongs to:

```text
engine/win_conditions.py
```

Examples:

```text
Prisoner submits correct flag
Prisoner accesses protected resource
Warden successfully prevents objective
Prisoner runs out of credits
Match timeout
```

For the initial implementation, the primary win condition can be:

```text
Prisoner submits the correct flag.
```

The engine should be the authority that determines whether the submitted flag is correct.

Never trust the Prisoner's self-reported success.

---

# 25. Match State

Match state should contain all mutable state required to resume/understand a match.

Conceptually:

```text
MatchState
├── match_id
├── status
├── current turn/scheduling state
├── turn/action number
├── prisoner state
├── warden state
├── active traps
├── actions/events
├── challenge information
├── start/end timestamps
├── winner
├── submitted flag
└── end reason
```

Match state belongs to the engine.

Sandbox state belongs to the sandbox.

Do not duplicate ownership unnecessarily.

---

# 26. Match Isolation

This is a critical invariant.

Every match must have:

```text
1 Match ID
1 Engine
1 MatchState
1 Sandbox
1 Prisoner
1 Warden
```

Sandbox operations must always be scoped by `match_id`.

For example:

```python
await sandbox_manager.run_command(
    match_id="match-123",
    ...
)
```

must never accidentally execute inside:

```text
match-456
```

The sandbox manager's internal registry should enforce this mapping.

---

# 27. Concurrency and Scaling

The initial architecture should support multiple concurrent matches.

For example:

```text
Maximum concurrency = 5

Match Queue
    │
    ├── Match A → Engine → Sandbox A
    ├── Match B → Engine → Sandbox B
    ├── Match C → Engine → Sandbox C
    ├── Match D → Engine → Sandbox D
    └── Match E → Engine → Sandbox E
```

A concurrency limit should prevent more than the configured number of active matches.

Initially this can be implemented with asynchronous workers and an `asyncio.Semaphore`.

Later this can move to:

* Celery
* Redis-backed workers
* Kubernetes jobs
* another distributed job system

without fundamentally changing the `Engine` or `SandboxManager` interfaces.

---

# 28. Important Process Boundary Detail

A "singleton" `SandboxManager` means one instance **per Python process**.

If there are five separate worker processes:

```text
Worker 1 → SandboxManager 1
Worker 2 → SandboxManager 2
Worker 3 → SandboxManager 3
Worker 4 → SandboxManager 4
Worker 5 → SandboxManager 5
```

This is normal.

Python objects cannot be shared between independent processes.

Do not introduce an external centralized sandbox registry until it is actually required.

---

# 29. Error Handling

Errors should be represented explicitly.

Tool execution failures should generally become `ToolResult` failures rather than crashing the entire match.

Example:

```python
ToolResult(
    success=False,
    output="",
    error="Permission denied",
    cost=1,
)
```

Infrastructure failures are different.

For example:

```text
Solari API unavailable
Sandbox destroyed unexpectedly
Monitoring system failed
```

may require the match to enter:

```text
ERROR
```

and trigger cleanup.

Always ensure sandbox cleanup occurs even when a match fails.

Use a `finally` block around the match lifecycle where appropriate.

---

# 30. Sandbox Cleanup

When a match finishes for any reason:

```text
PRISONER_WON
WARDEN_WON
TIMEOUT
ERROR
```

the sandbox must eventually be destroyed.

Conceptually:

```python
try:
    await engine.run()
finally:
    await sandbox_manager.destroy_sandbox(match_id)
```

The sandbox registry should remove the match entry after successful destruction.

Avoid leaving orphaned sandboxes.

---

# 31. Logging

Logs should be useful for debugging the match runtime.

Log important lifecycle events:

```text
Sandbox created
Sandbox setup started
Sandbox setup completed
Match started
Agent action
Tool execution
Tool result
Trap armed
Trap triggered
Credits changed
Match ended
Sandbox destroyed
```

Do not log secrets unnecessarily.

Do not log private LLM chain-of-thought.

A concise reasoning summary may be logged if explicitly produced by the agent, but internal model reasoning must not be treated as an observable game event.

---

# 32. Observability

The backend should distinguish between:

### Internal state

Used by the engine:

```text
credits
cooldowns
trap state
scheduler state
```

### Match events

Safe structured information about what happened:

```text
tool called
command executed
file changed
trap triggered
flag submitted
```

### Agent private reasoning

Not exposed.

The eventual frontend can subscribe to match events rather than directly inspecting engine internals.

This will make WebSocket/SSE integration significantly easier later.

---

# 33. Database and API

The initial implementation should **not** depend on the database or API layer.

First make this work:

```text
main.py
   ↓
Challenge
   ↓
Sandbox
   ↓
Engine
   ↓
Prisoner + Warden
   ↓
Complete Match
   ↓
Winner
   ↓
Cleanup
```

Only after the core pipeline works should the backend add:

```text
FastAPI
PostgreSQL
persistent match state
authentication
WebSockets
frontend integration
```

Persistence should consume match state/events rather than becoming tightly coupled to game execution.

---

# 34. Current Development Priority

Implement the backend in this order:

## Phase 1 — Sandbox

Implement:

```text
sandbox/models.py
sandbox/client.py
sandbox/manager.py
sandbox/monitor.py
```

Verify that we can:

1. Create a Solari sandbox.
2. Execute commands.
3. Read/write files.
4. Create the required users/environment.
5. Monitor relevant events.
6. Destroy the sandbox.

---

## Phase 2 — Tools

Implement:

```text
agents/tools/
```

with:

* tool schemas
* registry
* execution
* filesystem tools
* shell tools
* process tools
* network tools
* system/trap tools

Verify authorization and tool costs.

---

## Phase 3 — Agents

Implement:

```text
PrisonerAgent
WardenAgent
```

with structured PydanticAI output.

The agents should be capable of selecting tools but should not directly modify game state.

---

## Phase 4 — Engine

Implement:

```text
MatchState
MatchEvent
EventBus
CreditManager
CooldownManager
Scheduler
TrapManager
ReactionManager
WinConditionManager
Engine
```

Start with the minimum viable versions.

Do not over-engineer the first implementation.

---

## Phase 5 — End-to-End Match

Implement one deterministic challenge.

Example:

```text
/root/secret.txt
    owner: root
    permissions: 600

Prisoner
    no sudo

Warden
    sudo

Goal
    obtain and submit the flag
```

Run:

```text
Challenge
    ↓
Sandbox setup
    ↓
Agents start
    ↓
Concurrent actions
    ↓
Tool calls
    ↓
Credits/cooldowns
    ↓
Sandbox events
    ↓
Traps/reactions
    ↓
Flag submission
    ↓
Winner
    ↓
Cleanup
```

Only proceed to API/database/frontend after this works.

---

# 35. Design Rules for Coding Agents

When modifying this backend, follow these rules.

### Rule 1 — Keep domain boundaries clear

Do not move logic between:

```text
agents
sandbox
engine
```

without a concrete architectural reason.

### Rule 2 — Engine owns game state

Agents and tools must not directly mutate match state.

### Rule 3 — Sandbox owns sandbox state

Engine should not manipulate raw Solari internals unless absolutely necessary.

### Rule 4 — Use structured models

Prefer Pydantic models and enums over loose dictionaries when the structure is stable.

### Rule 5 — Do not trust the LLM

The LLM chooses actions.

The backend validates:

* tool availability
* parameters
* permissions
* credits
* cooldowns
* game rules

### Rule 6 — Do not use prompts as security boundaries

If the Prisoner cannot use `kill_process`, enforce that in code.

Never rely solely on:

```text
"You cannot use kill_process."
```

in the system prompt.

### Rule 7 — Do not expose chain-of-thought

Only expose structured actions, tool calls/results, events, and concise summaries where appropriate.

### Rule 8 — Match isolation is mandatory

Always associate sandbox operations with a match ID.

### Rule 9 — Cleanup is mandatory

Every sandbox created for a match must eventually be destroyed.

### Rule 10 — Avoid premature abstraction

Do not create a class/file solely because it might be useful later.

For example, if sandbox setup is currently one cohesive operation, keep it in `SandboxManager` rather than immediately creating a `SandboxBuilder`.

Extract components when complexity actually warrants it.

---

# 36. Target Architecture

The desired end state of the core runtime is:

```text
                    MATCH QUEUE
                         │
                         ▼
                ┌────────────────┐
                │ Worker / Runner │
                └───────┬────────┘
                        │
                        ▼
                 ┌──────────────┐
                 │    Engine    │
                 │  Match #123  │
                 └──────┬───────┘
                        │
             ┌──────────┼──────────┐
             │          │          │
             ▼          ▼          ▼
        Prisoner      Warden    EventBus
             │          │          │
             └──────┬───┘          │
                    ▼              │
              Tool Registry        │
                    │              │
                    ▼              │
             Tool Execution        │
                    │              │
                    ▼              │
             SandboxManager ◄───────┘
                    │
                    ▼
              SolariClient
                    │
                    ▼
              Solari Sandbox
                    │
                    ▼
             SandboxMonitor
                    │
                    ▼
              SandboxEvent
                    │
                    └──────────────► EventBus
```

The most important architectural principle is:

> **The Engine runs the game, Agents make decisions, Tools provide capabilities, and the Sandbox provides isolation.**

Everything else should support this separation rather than blur it.
