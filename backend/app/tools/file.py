from app.tools.base import BaseTool, ToolRegistry
from app.tools.models import ToolResult


class ReadFileTool(BaseTool):
    """Read the contents of a file."""

    name = "read_file"
    description = "Read the contents of a file. Be careful with large files."
    agent_type = "both"
    params_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file",
            }
        },
        "required": ["path"],
    }

    async def execute(self, sandbox_manager, match_id: str, params: dict) -> ToolResult:
        path = params.get("path", "")
        try:
            result = await sandbox_manager.run_command(
                match_id=match_id,
                command=f"cat '{path}' 2>&1",
                user=getattr(self, "_current_user", "root"),
                timeout=10,
            )

            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            exit_code = result.get("exit_code", 1)

            if exit_code != 0:
                return ToolResult(
                    success=False,
                    error=stderr or stdout or "Permission denied",
                    cost=self.cost,
                )

            return ToolResult(
                success=True,
                output=stdout,
                cost=self.cost,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                cost=self.cost,
            )


class WriteFileTool(BaseTool):
    """Write content to a file. Prisoner can only write to /home/prisoner/ and /tmp/."""

    name = "write_file"
    description = "Write content to a file. Prisoner can only write to /home/prisoner/ and /tmp/. Warden can write anywhere."
    agent_type = "both"
    params_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to write to",
            },
            "content": {
                "type": "string",
                "description": "Content to write",
            },
        },
        "required": ["path", "content"],
    }

    async def execute(self, sandbox_manager, match_id: str, params: dict) -> ToolResult:
        path = params.get("path", "")
        content = params.get("content", "")

        try:
            # Escape single quotes for shell heredoc
            escaped = content.replace("'", "'\\''")
            cmd = f"cat > '{path}' << 'EOF'\n{escaped}\nEOF"

            result = await sandbox_manager.run_command(
                match_id=match_id,
                command=cmd,
                user=getattr(self, "_current_user", "root"),
                timeout=10,
            )

            if result.get("exit_code", 1) != 0:
                return ToolResult(
                    success=False,
                    error=result.get("stderr", "Permission denied or invalid path"),
                    cost=self.cost,
                )

            return ToolResult(
                success=True,
                output=f"Written {len(content)} bytes to {path}",
                cost=self.cost,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                cost=self.cost,
            )


class ListDirTool(BaseTool):
    """List directory contents with details."""

    name = "list_dir"
    description = "List directory contents with details (ls -la)."
    agent_type = "both"
    params_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list",
            }
        },
        "required": ["path"],
    }

    async def execute(self, sandbox_manager, match_id: str, params: dict) -> ToolResult:
        path = params.get("path", ".")
        try:
            result = await sandbox_manager.run_command(
                match_id=match_id,
                command=f"ls -la '{path}' 2>&1",
                user=getattr(self, "_current_user", "root"),
                timeout=10,
            )

            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")

            if result.get("exit_code", 1) != 0:
                return ToolResult(
                    success=False,
                    error=stderr or stdout,
                    cost=self.cost,
                )

            return ToolResult(
                success=True,
                output=stdout,
                cost=self.cost,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                cost=self.cost,
            )


ToolRegistry.register(ReadFileTool())
ToolRegistry.register(WriteFileTool())
ToolRegistry.register(ListDirTool())
