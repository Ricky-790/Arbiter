"""Shared agent-facing domain models.

These enums deliberately contain no match state or execution behaviour.  The
engine will later use them when validating a tool call.
"""

from enum import Enum


class AgentType(str, Enum):
    PRISONER = "prisoner"
    WARDEN = "warden"


class ActionType(str, Enum):
    BASH = "bash"
    WATCH_FILE = "watch_file"
    WATCH_PROCESS = "watch_process"
    KILL_PROCESS = "kill_process"
    AUTO_KILL = "auto_kill"
    BLOCK_NETWORK = "block_network"
    SUBMIT_FLAG = "submit_flag"
    PASS = "pass"
