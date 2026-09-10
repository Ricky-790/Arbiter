"""Models shared by the agent tool layer."""

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field


class ToolCost(IntEnum):
    """Credit costs exposed as tool metadata; tools never deduct them."""

    BASH = 2
    READ_FILE = 0
    WRITE_FILE = 0
    WRITE_SCRATCHPAD = 0
    WATCH_FILE = 3
    WATCH_PROCESS = 4
    KILL_PROCESS = 5
    AUTO_KILL = 15
    BLOCK_NETWORK = 8
    SUBMIT_FLAG = 0
    PASS = 0


class ToolCall(BaseModel):
    """An agent's requested capability and LLM-controlled arguments."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(
        default="",
        description=(
            "Detailed reasoning behind this decision: what you observed in recent tool results and scratchpad, why you chose this tool, why these arguments, and what you expect to learn. Always explain your thinking here; it is shown back to you next turn."
        ),
    )


class ToolResult(BaseModel):
    """The safe, structured result returned from an attempted tool action."""

    success: bool
    output: str = ""
    error: str | None = None
    exit_code: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    notice: str | None = Field(
        default=None,
        description=(
            "Optional guidance attached when the output exceeded token "
            "limits (e.g. it will be hidden next turn)."
        ),
    )
