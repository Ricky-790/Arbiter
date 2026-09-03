import asyncio

from app.tools.base import BaseTool, ToolRegistry
from app.tools.models import ToolResult


class BashTool(BaseTool):
    """Execute a bash command in the sandbox."""

    name: str = "bash"
    description: str = "Execute a bash command in the sandbox. Use this for system exploration, file operations, and running programs."
    agent_type: str = "both"
    params_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute",
            }
        },
        "required": ["command"],
    }

    async def execute(self, sandbox_manager, match_id: str, params: dict) -> ToolResult:
        command = params.get("command", "")
        if not command:
            return ToolResult(
                success=False,
                error="No command provided",
                cost=self.cost,
            )

        try:
            result = await sandbox_manager.run_command(
                match_id=match_id,
                command=command,
                user=getattr(self, "_current_user", "root"),
                timeout=30,
            )

            return ToolResult(
                success=result.get("exit_code", 1) == 0,
                output=result.get("stdout", ""),
                error=result.get("stderr", "")
                if result.get("exit_code", 1) != 0
                else None,
                cost=self.cost,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error="Command timed out after 30s",
                cost=self.cost,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                cost=self.cost,
            )


ToolRegistry.register(BashTool())
