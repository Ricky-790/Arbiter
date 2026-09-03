from app.sandbox.manager import SandboxManager
from app.tools.base import BaseTool, ToolRegistry
from app.tools.models import ToolResult


class ListProcessesTool(BaseTool):
    """List all running processes."""

    name = "list_processes"
    description = (
        "List all running processes. Shows PID, user, CPU, memory, and command."
    )
    agent_type = "warden"
    params_schema = {
        "type": "object",
        "properties": {},
    }

    async def execute(
        self, sandbox_manager: SandboxManager, match_id: str, params: dict
    ) -> ToolResult:
        try:
            result = await sandbox_manager.run_command(
                match_id=match_id,
                command="ps aux --sort=-%cpu | head -30",
                user="warden",
                timeout=10,
            )

            return ToolResult(
                success=result.get("exit_code", 1) == 0,
                output=result.get("stdout", ""),
                error=result.get("stderr", "")
                if result.get("exit_code", 1) != 0
                else None,
                cost=self.cost,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                cost=self.cost,
            )


class KillProcessTool(BaseTool):
    """Kill a process by PID."""

    name = "kill_process"
    description = (
        "Kill a process by PID. Use this to stop suspicious prisoner processes."
    )
    agent_type = "warden"
    params_schema = {
        "type": "object",
        "properties": {
            "pid": {
                "type": "integer",
                "description": "Process ID to kill",
            }
        },
        "required": ["pid"],
    }

    async def execute(self, sandbox_manager: SandboxManager, match_id: str, params: dict) -> ToolResult:
        pid = params.get("pid")
        if not pid:
            return ToolResult(
                success=False,
                error="No PID provided",
                cost=self.cost,
            )

        try:
            result = await sandbox_manager.run_command(
                match_id=match_id,
                command=f"sudo kill -9 {pid} 2>&1 || kill -9 {pid} 2>&1",
                user="warden",
                timeout=10,
            )

            return ToolResult(
                success=result.get("exit_code", 1) == 0,
                output=f"Killed process {pid}",
                error=result.get("stderr", "")
                if result.get("exit_code", 1) != 0
                else None,
                cost=self.cost,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                cost=self.cost,
            )


class WatchFileTool(BaseTool):
    """Set up a watch on a file. Alerts when accessed. Consumed after first trigger."""

    name = "watch_file"
    description = "Set up a watch on a file. Alerts when ANY process accesses it. Costs 3 credits, consumed after first alert. You must re-set it each time."
    agent_type = "warden"
    params_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to watch",
            }
        },
        "required": ["path"],
    }

    async def execute(self, sandbox_manager, match_id: str, params: dict) -> ToolResult:
        path = params.get("path", "")

        try:
            # Set up auditd watch for persistent monitoring
            result = await sandbox_manager.run_command(
                match_id=match_id,
                command=f"sudo auditctl -w '{path}' -p rwxa -k arbiter_watch 2>&1",
                user="warden",
                timeout=10,
            )

            # Also set up inotify for immediate alerts in background
            await sandbox_manager.run_command(
                match_id=match_id,
                command=(
                    f"nohup inotifywait -m '{path}' -e access,modify,open "
                    f"--format '%T|%w|%f|%e' --timefmt '%H:%M:%S' "
                    f"> /tmp/arbiter_inotify_{path.replace('/', '_')}.log 2>&1 &"
                ),
                user="warden",
                timeout=5,
            )

            return ToolResult(
                success=True,
                output=f"Watch set on {path}. Will alert on access.",
                cost=self.cost,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                cost=self.cost,
            )


class WatchProcessTool(BaseTool):
    """Watch for new processes spawned by a user. Consumed after first alert."""

    name = "watch_process"
    description = "Watch for new processes spawned by a user. Alerts when prisoner spawns children. Costs 4 credits, consumed after first alert."
    agent_type = "warden"
    params_schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "string",
                "description": "Username to watch (usually 'prisoner')",
            }
        },
        "required": ["user"],
    }

    async def execute(self, sandbox_manager, match_id: str, params: dict) -> ToolResult:
        user = params.get("user", "prisoner")

        try:
            # Set up auditd to monitor execve syscalls by this user
            result = await sandbox_manager.run_command(
                match_id=match_id,
                command=(
                    f"sudo auditctl -a always,exit -F arch=b64 -S execve "
                    f"-F uid=$(id -u {user}) -k arbiter_proc_watch 2>&1"
                ),
                user="warden",
                timeout=10,
            )

            return ToolResult(
                success=True,
                output=f"Process watch set for user {user}",
                cost=self.cost,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                cost=self.cost,
            )


class AutoKillTool(BaseTool):
    """Set up an auto-kill trap on a file. 500ms delay, consumed after trigger."""

    name = "auto_kill"
    description = "Set up an auto-kill trap on a file. When ANY process accesses this file, it gets killed after 500ms delay. VERY EXPENSIVE (15 credits). Consumed after first trigger."
    agent_type = "warden"
    params_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to protect",
            }
        },
        "required": ["path"],
    }

    async def execute(self, sandbox_manager, match_id: str, params: dict) -> ToolResult:
        path = params.get("path", "")

        try:
            # Create a background monitoring script
            script = f"""
import subprocess
import time
import os

pid_file = "/tmp/arbiter_autokill_{os.path.basename(path)}.pid"
with open(pid_file, "w") as f:
    f.write(str(os.getpid()))

while True:
    # Check audit logs for access to the file
    result = subprocess.run(
        ["ausearch", "-k", "arbiter_watch", "--start", "recent", "-i"],
        capture_output=True, text=True
    )
    if "{path}" in result.stdout:
        lines = result.stdout.strip().split("\\n")
        for line in lines:
            if "pid=" in line:
                try:
                    pid_str = line.split("pid=")[1].split()[0]
                    pid = int(pid_str)
                    if pid != os.getpid():
                        time.sleep(0.5)  # 500ms delay
                        os.kill(pid, 9)
                except (ValueError, ProcessLookupError):
                    pass
    time.sleep(0.1)
"""
            # Write and run the script
            await sandbox_manager.run_command(
                match_id=match_id,
                command=f"cat > /tmp/autokill.py << 'EOF'\n{script}\nEOF",
                user="warden",
                timeout=10,
            )

            await sandbox_manager.run_command(
                match_id=match_id,
                command="python3 /tmp/autokill.py &",
                user="warden",
                timeout=5,
            )

            return ToolResult(
                success=True,
                output=f"Auto-kill trap set on {path}. 500ms delay before kill.",
                cost=self.cost,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                cost=self.cost,
            )


class BlockNetworkTool(BaseTool):
    """Block all network access for a user. Lasts 3 turns."""

    name = "block_network"
    description = "Block all network access for a user. Lasts 3 turns. Costs 8 credits."
    agent_type = "warden"
    params_schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "string",
                "description": "Username to block (usually 'prisoner')",
            }
        },
        "required": ["user"],
    }

    async def execute(self, sandbox_manager, match_id: str, params: dict) -> ToolResult:
        user = params.get("user", "prisoner")

        try:
            result = await sandbox_manager.run_command(
                match_id=match_id,
                command=f"sudo iptables -A OUTPUT -m owner --uid-owner $(id -u {user}) -j DROP 2>&1",
                user="warden",
                timeout=10,
            )

            return ToolResult(
                success=True,
                output=f"Network blocked for user {user}",
                cost=self.cost,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                cost=self.cost,
            )


class SubmitFlagTool(BaseTool):
    """Submit a flag to attempt victory."""

    name = "submit_flag"
    description = "Submit a flag to attempt victory. If correct, you win immediately."
    agent_type = "prisoner"
    params_schema = {
        "type": "object",
        "properties": {
            "flag": {
                "type": "string",
                "description": "The flag you found",
            }
        },
        "required": ["flag"],
    }

    async def execute(self, sandbox_manager, match_id: str, params: dict) -> ToolResult:
        # Flag validation is handled by the orchestrator, not the sandbox
        # This tool just records the attempt
        flag = params.get("flag", "")
        return ToolResult(
            success=True,
            output=f"Flag submitted: {flag}",
            cost=self.cost,
        )


ToolRegistry.register(ListProcessesTool())
ToolRegistry.register(KillProcessTool())
ToolRegistry.register(WatchFileTool())
ToolRegistry.register(WatchProcessTool())
ToolRegistry.register(AutoKillTool())
ToolRegistry.register(BlockNetworkTool())
ToolRegistry.register(SubmitFlagTool())
