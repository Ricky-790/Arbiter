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
    PEEK_PRISONER_LOGS = 2


class ToolCall(BaseModel):
    """An agent's requested capability and LLM-controlled arguments.

    This is the Engine-internal representation of a native Pydantic AI tool
    call -- the model never produces it directly.
    """

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    #: The native tool-call id, when the call came from a model. Persisted so a
    #: fork can line a match event up with the agent's stored conversation.
    tool_call_id: str | None = None
    #: Groups the calls one model response emitted together. Pydantic AI
    #: returns their results in a single message, so they are atomic: a replay
    #: must not stop between them, and a fork snaps to the batch's last call.
    batch_id: str | None = None


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
            "Optional guidance attached when the output is long (e.g. a "
            "suggestion to use the scratchpad and narrower commands)."
        ),
    )
