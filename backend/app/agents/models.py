from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    PRISONER = "prisoner"
    WARDEN = "warden"


class ActionType(str, Enum):
    BASH = "bash"
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    LIST_DIR = "list_dir"
    PYTHON = "python"
    LIST_PROCESSES = "list_processes"
    KILL_PROCESS = "kill_process"
    WATCH_FILE = "watch_file"
    WATCH_PROCESS = "watch_process"
    AUTO_KILL = "auto_kill"
    BLOCK_NETWORK = "block_network"
    SUBMIT_FLAG = "submit_flag"
    PASS = "pass"


class GameStatus(str, Enum):
    SETUP = "setup"
    RUNNING = "running"
    PRISONER_WON = "prisoner_won"
    WARDEN_WON = "warden_won"
    TIMEOUT = "timeout"
    ERROR = "error"


class TurnState(str, Enum):
    PRISONER = "prisoner"
    WARDEN = "warden"


class ToolResult(BaseModel):
    success: bool
    output: str = ""
    error: str | None = None
    cost: int = 0


class GameAction(BaseModel):
    turn_number: int
    actor: AgentType
    action_type: ActionType
    params: dict[str, Any] = Field(default_factory=dict)
    result: ToolResult
    credits_before: int
    credits_after: int
    timestamp: datetime = Field(default_factory=datetime.now(timezone.utc))
    alert_triggered: str | None = None


class TrapType(str, Enum):
    WATCH_FILE = "watch_file"
    WATCH_PROCESS = "watch_process"
    AUTO_KILL = "auto_kill"
    BLOCK_NETWORK = "block_network"


class Trap(BaseModel):
    trap_type: TrapType
    target: str
    cost: int
    set_at_turn: int
    consumed: bool = False
    triggered_at: int | None = None


class AgentState(BaseModel):
    agent_type: AgentType
    credits: int
    is_alive: bool = True
    current_pid: int | None = None


class MatchState(BaseModel):
    match_id: str
    status: GameStatus = GameStatus.SETUP
    current_turn: TurnState = TurnState.PRISONER
    turn_number: int = 0
    prisoner: AgentState
    warden: AgentState
    actions: list[GameAction] = []
    active_traps: list[Trap] = []
    challenge_id: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    winner: AgentType | None = None
    flag: str | None = None
    reason: str | None = None


# --- SIMPLIFIED: Only what the setup agent needs ---


class ChallengeConfig(BaseModel):
    """Minimal challenge description passed to setup_match()."""

    win_condition: str = Field(
        description="What the prisoner must do to win, e.g. 'read /root/secret.txt'"
    )
    difficulty: str = Field(default="medium", description="easy, medium, or hard")
    theme: str | None = Field(
        default=None, description="Optional theme hint, e.g. 'symlink race'"
    )


class ChallengeSetup(BaseModel):
    """Output from the setup agent."""

    reasoning: str = Field(description="How the challenge works and how to exploit it")
    setup_script: str = Field(
        description="Bash script that sets up the sandbox environment"
    )
    flag: str = Field(description="The secret flag the prisoner must submit")
    expected_solution: str = Field(
        description="Brief description of the intended exploit path"
    )
