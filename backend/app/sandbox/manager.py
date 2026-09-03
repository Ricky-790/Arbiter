import os
from typing import Any

from dotenv import load_dotenv
from solari_sandbox import Sandbox, SandboxClient

from app.logger import get_logger

logger = get_logger()

load_dotenv()


class SandboxManager:
    def __init__(self):
        self.sandboxes: dict[str, Sandbox] = {}
        self.client: SandboxClient = SandboxClient(
            api_key=os.getenv("SOLARI_API_KEY", ""),
            base_url="https://api.getsolari.com",
        )

    async def get_sandbox(self, match_id: str):
        sbx = self.sandboxes.get(match_id, None)
        if sbx is None:
            sbx = await self._create_sandbox()  # Pass sbx config
            self.sandboxes[match_id] = sbx
            logger.info(
                f"Created a new sandbox. Currently active: {len(self.sandboxes)}"
            )
        return sbx.sandboxId

    async def _create_sandbox(self) -> Sandbox:
        sbx = await self.client.create(template="base", cpu=2)
        return sbx

    async def destroy_sandbox(self, match_id: str):
        sbx = self.sandboxes.get(match_id, None)
        if sbx is not None:
            await sbx.kill()
            del self.sandboxes[match_id]
            logger.info(
                f"Destroyed sandbox for match {match_id}. Currently active: {len(self.sandboxes)}"
            )

    async def _setup_challenge(self):
        pass

    async def run_command(
        self, match_id: str, command: str, user: str = "root", timeout: int = 30
    ) -> dict[str, Any]:
        sbx = self.sandboxes.get(match_id)
        if not sbx:
            raise ValueError(f"No sandbox for match {match_id}")

        if user != "root":
            command = f"su - {user} -c '{command}'"

        # Execute via Solari SDK
        await sbx.connect()
        if not sbx.connected:
            await sbx.reconnect()
        result = await sbx.commands.run(
            "bash", args=["-c", command], timeout_ms=timeout * 1000
        )
        await sbx.close()
        return {
            "stdout": result.stdout if hasattr(result, "stdout") else str(result),
            "stderr": result.stderr if hasattr(result, "stderr") else "",
            "exit_code": result.exitCode if hasattr(result, "exitCode") else 0,
        }


# Singleton instance of SandboxManager
sandbox_manager = SandboxManager()
