"""Thin adapter around the Solari SDK."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable

from dotenv import load_dotenv
from solari_core import CodeLanguage
from solari_sandbox import RunCodeResult, Sandbox, SandboxClient

from .models import CommandResult, SandboxConfig

load_dotenv()


class SolariClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("SOLARI_API_KEY", "")
        self.base_url = os.getenv("SOLARI_BASE_URL", "https://api.getsolari.com")
        self._client: SandboxClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None

    @property
    def client(self) -> SandboxClient:
        """The SDK client for the loop that is currently running.

        The SDK client owns an ``httpx.AsyncClient``, whose connection pool is
        tied to the event loop it first ran on. A Celery worker serves every
        match in its own ``asyncio.run()`` loop, so reusing a client built on
        a previous, now-closed loop fails with ``Event loop is closed``.
        Rebuild it whenever the running loop changes; within one loop the
        client is cached and reused as before.
        """
        loop = asyncio.get_running_loop()
        if self._client is None or self._client_loop is not loop:
            self._client = SandboxClient(api_key=self.api_key, base_url=self.base_url)
            self._client_loop = loop
        return self._client

    async def create(
        self, config: SandboxConfig | None = None, *, from_snapshot: str | None = None
    ) -> Sandbox:
        if config is None:
            config = SandboxConfig()
        sbx: Sandbox = await self.client.create(
            template=config.template,
            cpu=config.cpu,
            mem_mb=config.mem_mb,
            from_snapshot=from_snapshot,
        )
        await sbx.connect()
        return sbx

    async def snapshot(self, sbx: Sandbox, *, name: str | None = None) -> str:
        """Save the sandbox's current state and return the Solari snapshot id.

        The sandbox keeps running, and a snapshot is self-contained, so it
        outlives the sandbox this match destroys. The SDK drops
        ``from_snapshot=None`` from the create body, so passing ``None`` above
        means "bare template".
        """
        return await sbx.snapshot(name)

    async def kill(self, sbx: Sandbox) -> None:
        # pass
        await sbx.kill()

    async def exec_command(
        self, sbx: Sandbox, *, command: str, user: str | None = None
    ) -> CommandResult:
        """Run an arbitrary shell command and normalize Solari's camelCase result."""
        result = await sbx.commands.run("sh", args=["-c", command], user=user)
        return CommandResult(
            exit_code=result.exitCode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    async def exec_code(
        self,
        sbx: Sandbox,
        *,
        code: str,
        language: CodeLanguage | None = None,
        context_id: str | None = None,
    ) -> RunCodeResult:
        return await sbx.run_code(code, language=language, context_id=context_id)

    async def read_file(self, sbx: Sandbox, *, path: str) -> str:
        return await sbx.files.read_text(path)

    async def write_file(
        self, sbx: Sandbox, *, path: str, content: str, mode: int | None = None
    ) -> None:
        await sbx.files.write(path, content, mode)

    async def watch_file(
        self, sbx: Sandbox, *, path: str, callback: Callable[[object], None]
    ) -> Callable[[], Awaitable[None]]:
        return await sbx.files.watch(path, callback, recursive=True)
