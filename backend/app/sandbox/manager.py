import asyncio
import shlex
from collections.abc import Awaitable, Callable

from solari_core import CodeLanguage
from solari_sandbox import Sandbox

from app.agents.tools.models import ToolResult
from app.logger import get_logger

from .client import SolariClient
from .models import CommandResult, SandboxConfig
from .monitor import EventHandler, SandboxMonitor

logger = get_logger()


class SandboxManager:
    """Shared sandbox infrastructure and concrete execution boundary for tools."""

    def __init__(self, client: SolariClient | None = None) -> None:
        self.client = client or SolariClient()
        self.sandboxes: dict[str, Sandbox] = {}
        self._file_unwatchers: dict[str, list[Callable[[], Awaitable[None]]]] = {}
        self._process_watches: dict[str, set[str]] = {}
        self._auto_kill_rules: dict[str, set[str]] = {}
        self._monitors: dict[str, SandboxMonitor] = {}
        self._process_tasks: dict[str, asyncio.Task[None]] = {}

    def set_event_handler(self, match_id: str, handler: EventHandler) -> None:
        self._monitors[match_id] = SandboxMonitor(match_id, handler)

    async def create_new_sandbox(
        self, match_id: str, config: SandboxConfig | None = None
    ) -> Sandbox:
        """Create a new sandbox instance"""
        sbx: Sandbox | None = self.sandboxes.get(match_id, None)
        if sbx:
            logger.error(f"A sandbox instance for match_id: {match_id} already exists")
            raise ValueError(
                f"A sandbox instance for match_id: {match_id} already exists"
            )
        config = SandboxConfig() if config is None else config
        sbx = await self.client.create(config=config)
        self.sandboxes[match_id] = sbx
        logger.info(f"Sandbox created. Currently active: {len(self.sandboxes)}")
        return sbx

    async def get_or_create_sandbox(
        self, match_id: str, config: SandboxConfig | None = None
    ) -> Sandbox:
        """Return the match sandbox, creating it exactly once when absent."""
        existing = self.sandboxes.get(match_id)
        if existing is not None:
            return existing
        return await self.create_new_sandbox(match_id, config)

    async def get_sandbox(self, match_id: str) -> Sandbox:
        try:
            return self.sandboxes[match_id]
        except KeyError as error:
            raise KeyError(f"No sandbox exists for match {match_id!r}") from error

    async def destroy_sandbox(self, match_id: str) -> None:
        sbx = await self.get_sandbox(match_id)
        for unwatch in self._file_unwatchers.pop(match_id, []):
            await unwatch()
        await self.client.kill(sbx)
        self.sandboxes.pop(match_id, None)
        self._process_watches.pop(match_id, None)
        self._auto_kill_rules.pop(match_id, None)
        self._monitors.pop(match_id, None)
        task = self._process_tasks.pop(match_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        logger.info(f"Sandbox destroyed. Currently active: {len(self.sandboxes)}")

    async def run_command(
        self, *, match_id: str, command: str, user: str
    ) -> ToolResult:
        result = await self.client.exec_command(
            await self.get_sandbox(match_id), command=command, user=user
        )
        return self._tool_result(result)

    async def run_code(
        self,
        *,
        match_id: str,
        code: str,
        language: CodeLanguage | None = None,
        context_id: str | None = None,
    ):
        return await self.client.exec_code(
            await self.get_sandbox(match_id),
            code=code,
            language=language,
            context_id=context_id,
        )

    async def read_file(self, *, match_id: str, path: str) -> str:
        return await self.client.read_file(await self.get_sandbox(match_id), path=path)

    async def write_file(
        self, *, match_id: str, path: str, content: str, mode: int | None = None
    ) -> None:
        await self.client.write_file(
            await self.get_sandbox(match_id), path=path, content=content, mode=mode
        )

    async def watch_file(self, *, match_id: str, path: str) -> ToolResult:
        sbx = await self.get_sandbox(match_id)

        def on_change(event: object) -> None:
            monitor = self._monitors.get(match_id)
            if monitor is not None:
                asyncio.create_task(monitor.publish_file_event(event))

        unwatch = await self.client.watch_file(sbx, path=path, callback=on_change)
        self._file_unwatchers.setdefault(match_id, []).append(unwatch)
        return ToolResult(success=True, output=f"Watching {path}")

    async def watch_process(self, *, match_id: str, process: str) -> ToolResult:
        await self.get_sandbox(match_id)
        self._process_watches.setdefault(match_id, set()).add(process)
        self._ensure_process_monitor(match_id)
        return ToolResult(success=True, output=f"Watching process {process}")

    async def kill_process(self, *, match_id: str, pid: int) -> ToolResult:
        return await self.run_command(
            match_id=match_id, command=f"kill {pid}", user="root"
        )

    async def auto_kill(self, *, match_id: str, process: str) -> ToolResult:
        await self.get_sandbox(match_id)
        self._auto_kill_rules.setdefault(match_id, set()).add(process)
        self._ensure_process_monitor(match_id)
        return ToolResult(success=True, output=f"Auto-kill rule armed for {process}")

    async def block_network(
        self, *, match_id: str, ip: str | None = None, port: int | None = None
    ) -> ToolResult:
        if ip is None:
            command = "iptables -P OUTPUT DROP"
        elif port is None:
            command = f"iptables -A OUTPUT -d {shlex.quote(ip)} -j DROP"
        else:
            command = (
                f"iptables -A OUTPUT -d {shlex.quote(ip)} -p tcp --dport {port} -j DROP"
            )
        return await self.run_command(match_id=match_id, command=command, user="root")

    @staticmethod
    def _tool_result(result: CommandResult) -> ToolResult:
        return ToolResult(
            success=result.ok,
            output=result.stdout,
            error=(result.stderr or f"Command exited with code {result.exit_code}")
            if not result.ok
            else None,
            exit_code=result.exit_code,
            metadata={"stderr": result.stderr} if result.stderr else {},
        )

    def _ensure_process_monitor(self, match_id: str) -> None:
        task = self._process_tasks.get(match_id)
        if task is None or task.done():
            self._process_tasks[match_id] = asyncio.create_task(
                self._poll_processes(match_id)
            )

    async def _poll_processes(self, match_id: str) -> None:
        seen: set[tuple[int, str]] = set()
        try:
            while match_id in self.sandboxes:
                result = await self.client.exec_command(
                    await self.get_sandbox(match_id),
                    command="ps -eo pid=,comm=",
                    user="root",
                )
                current = self._parse_processes(result)
                new_processes = current - seen
                seen = current
                monitor = self._monitors.get(match_id)
                watched = self._process_watches.get(match_id, set())
                auto_kill = self._auto_kill_rules.get(match_id, set())
                for pid, process in new_processes:
                    if process in auto_kill:
                        await self.kill_process(match_id=match_id, pid=pid)
                    if process in watched and monitor is not None:
                        await monitor.publish_process_started(pid, process)
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(f"Process monitoring failed for match {match_id}")

    @staticmethod
    def _parse_processes(result: CommandResult) -> set[tuple[int, str]]:
        if not result.ok:
            return set()
        processes: set[tuple[int, str]] = set()
        for line in result.stdout.splitlines():
            fields = line.split(maxsplit=1)
            if len(fields) != 2:
                continue
            try:
                processes.add((int(fields[0]), fields[1]))
            except ValueError:
                continue
        return processes


# Singleton instance of SandboxManager
sandbox_manager = SandboxManager()
