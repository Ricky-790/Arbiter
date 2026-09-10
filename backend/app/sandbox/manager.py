import asyncio
import base64
import shlex
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath

from solari_core import CodeLanguage
from solari_sandbox import Sandbox

from app import sandbox
from app.agents.tools.models import ToolResult
from app.logger import get_logger

from .client import SolariClient
from .models import ChallengeSpec, CommandResult, SandboxConfig
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

    async def read_file(self, *, match_id: str, path: str, user: str) -> ToolResult:
        """Read a file inside the sandbox as the acting user.

        Executed via a shell command under ``user`` so OS permissions apply.
        The privileged ``files`` API is deliberately not used here because it
        would bypass prisoner/warden permissions.
        """
        try:
            validated_path = self._validate_path(path, user)
            return await self.run_command(
                match_id=match_id,
                command=f"cat -- {shlex.quote(validated_path)}",
                user=user,
            )
        except ValueError as e:
            return ToolResult(success=False, error=str(e))

    async def write_file(
        self, *, match_id: str, path: str, content: str, user: str
    ) -> ToolResult:
        """Write content to a file inside the sandbox as the acting user.

        Parent directories are created as that same user, so unwritable
        locations fail instead of bypassing prisoner/warden permissions.
        """
        try:
            validated_path = self._validate_path(path, user)
            parent = str(PurePosixPath(validated_path).parent)
            encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
            mkdir = (
                f"mkdir -p -- {shlex.quote(parent)} && "
                if parent and parent != "."
                else ""
            )
            command = (
                f"{mkdir}printf '%s' {shlex.quote(encoded)} | base64 -d > "
                f"{shlex.quote(validated_path)}"
            )
            result = await self.run_command(
                match_id=match_id, command=command, user=user
            )
            if not result.success:
                return result
            return ToolResult(
                success=True, output=f"Wrote {len(content)} bytes to {validated_path}"
            )
        except ValueError as e:
            return ToolResult(success=False, error=str(e))

    async def write_to_scratchpad(
        self, *, match_id: str, content: str, user: str
    ) -> ToolResult:
        """Append content to the actor's private scratchpad as that user."""
        path = self._scratchpad_path(user)
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        command = (
            f"printf '%s' {shlex.quote(encoded)} | base64 -d >> "
            f"{shlex.quote(path)} && printf '\\n' >> {shlex.quote(path)}"
        )
        result = await self.run_command(match_id=match_id, command=command, user=user)
        if not result.success:
            return result
        return ToolResult(
            success=True, output=f"Appended {len(content)} bytes to scratchpad"
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
    def _scratchpad_path(user: str) -> str:
        return f"/home/{user}/scratchpad.txt"

    @staticmethod
    def _validate_path(path: str, user: str) -> str:
        if not path or "\x00" in path:
            raise ValueError("Invalid path")
        if path.__contains__("~"):
            raise ValueError("Cannont contain `~`")
        if path.startswith("/"):
            path = path.removeprefix("/")
        return f"/home/{user}/{path}"

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

# async def main():
#     await sandbox_manager.create_new_sandbox(match_id="test1")
#     challenge = ChallengeSpec(name="ctf", description="test", flag="hello")
#     commands = [
#         f"id -u {shlex.quote(challenge.warden_user)} >/dev/null 2>&1 || useradd -m -s /bin/bash {shlex.quote(challenge.warden_user)}",
#         f"usermod -aG sudo {shlex.quote(challenge.warden_user)}",
#         f"id -u {shlex.quote(challenge.prisoner_user)} >/dev/null 2>&1 || useradd -m -s /bin/bash {shlex.quote(challenge.prisoner_user)}",
#     ]
#     files = {"/root/secret.txt": challenge.flag, **challenge.files}
#     for path, content in files.items():
#         commands.append(
#             "install -d -m 700 "
#             f"{shlex.quote(str(Path(path).parent))} && "
#             f"printf %s {shlex.quote(content)} > {shlex.quote(path)} && chmod 600 {shlex.quote(path)}"
#         )
#     for command in commands:
#         result = await sandbox_manager.run_command(
#             match_id="test1", command=command, user="root"
#         )
#     result = await sandbox_manager.read_file(
#         match_id="test1", path="/root/secret.txt", user="prisoner"
#     )
#     logger.info(f"read_file result[prisoner]: {result}")
#     result = await sandbox_manager.read_file(
#         match_id="test1", path="/root/secret.txt", user="warden"
#     )
#     logger.info(f"read_file result[warden]: {result}")

#     result = await sandbox_manager.write_file(
#         match_id="test1",
#         path="~/root/abc.txt",
#         content="prisoner text",
#         user="prisoner",
#     )
#     logger.info(f"write_file result[prisoner] to root:{result}")
#     result = await sandbox_manager.write_file(
#         match_id="test1", path="/root/def.txt", content="warden text", user="warden"
#     )
#     logger.info(f"write_file result[warden] to root:{result}")
#     result = await sandbox_manager.write_file(
#         match_id="test1", path="abc.txt", content="prisoner text", user="prisoner"
#     )
#     logger.info(f"write_file result[prisoner]:{result}")
#     result = await sandbox_manager.write_file(
#         match_id="test1", path="def.txt", content="warden text", user="warden"
#     )
#     logger.info(f"write_file result[warden]:{result}")
#     result = await sandbox_manager.write_to_scratchpad(
#         match_id="test1", content="prisoner text", user="prisoner"
#     )
#     logger.info(f"write_file result[prisoner] to root:{result}")
#     result = await sandbox_manager.write_to_scratchpad(
#         match_id="test1", content="warden text", user="warden"
#     )
#     logger.info(f"write_file result[warden] to root:{result}")


# # import asyncio
# if __name__ == "__main__":
#     asyncio.run(main())
