from enum import Enum
from typing import Any, Dict, Optional


class ToolCost(Enum):
    """Credit costs for tools."""

    BASH = 2
    READ_FILE = 1
    WRITE_FILE = 2
    LIST_DIR = 1
    PYTHON = 3
    LIST_PROCESSES = 2
    KILL_PROCESS = 5
    WATCH_FILE = 3
    WATCH_PROCESS = 4
    AUTO_KILL = 15
    BLOCK_NETWORK = 8
    SUBMIT_FLAG = 0
    PASS = 0


class ToolResult:
    """Result of executing a tool."""

    def __init__(
        self,
        success: bool,
        output: str = "",
        error: Optional[str] = None,
        cost: int = 0,
    ):
        self.success = success
        self.output = output
        self.error = error
        self.cost = cost

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "cost": self.cost,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolResult":
        return cls(
            success=data.get("success", False),
            output=data.get("output", ""),
            error=data.get("error"),
            cost=data.get("cost", 0),
        )

    def __repr__(self) -> str:
        return f"ToolResult(success={self.success}, cost={self.cost})"
