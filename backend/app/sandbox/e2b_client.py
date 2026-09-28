"""Thin adapter around the E2B SDK.

Mirrors :mod:`app.sandbox.solari_client` so ``SandboxManager`` can run against
either provider without knowing which one it has. Where E2B has no equivalent
of a Solari feature the method is kept for interface parity and does nothing.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from dotenv import load_dotenv
from e2b import (
    AsyncSandbox,
    CommandExitException,
    FileNotFoundException,
    FilesystemEvent,
    FilesystemEventType,
    FileType,
)

from .models import CommandResult, SandboxConfig

load_dotenv()

#: E2B kills a sandbox ``timeout`` seconds after creation unless the deadline is
#: pushed back, and its default is only 5 minutes. Solari sandboxes live until
#: they are killed, so without this a match would be torn down mid-game. An hour
#: sits above the match wall-clock timeout and is the ceiling for Hobby
#: accounts; Pro accounts may raise it.
SANDBOX_TIMEOUT_SECONDS = 3600

#: Run commands with no deadline, matching Solari (which exposes no per-command
#: timeout). ``0`` disables the E2B command timeout; the sandbox lifetime above
#: still bounds the match.
COMMAND_TIMEOUT_SECONDS = 0

#: E2B reports its event type as an enum. The monitor maps plain strings, so
#: normalize to the vocabulary it already understands.
_EVENT_TYPES: dict[FilesystemEventType, str] = {
    FilesystemEventType.CREATE: "create",
    FilesystemEventType.WRITE: "write",
    FilesystemEventType.REMOVE: "delete",
    FilesystemEventType.RENAME: "modify",
    FilesystemEventType.CHMOD: "modify",
}


@dataclass(frozen=True)
class _FileEvent:
    """Provider-neutral view of one E2B filesystem event.

    ``SandboxMonitor.publish_file_event`` reads ``type``/``path`` off whatever
    the client hands it, so the adapter resolves E2B's enum type and its
    directory-relative name here rather than leaking either into the monitor.
    """

    type: str
    path: str


class E2BClient:
    """The E2B counterpart to ``SolariClient``.

    Unlike the Solari SDK, ``AsyncSandbox.create`` is a classmethod that builds
    its own API client per call and binds the connection config to the sandbox
    it returns, so there is no loop-bound client cached here: a Celery worker
    serving each match in a fresh ``asyncio.run()`` loop cannot inherit one from
    a closed loop.
    """

    def __init__(self) -> None:
        self.api_key = os.getenv("E2B_API_KEY", "")
        self.domain = os.getenv("E2B_DOMAIN", "")

    @property
    def _opts(self) -> dict[str, str]:
        """Connection overrides for sandbox creation.

        E2B falls back to the ambient ``E2B_API_KEY``/``E2B_DOMAIN`` when these
        are empty, so an unset environment behaves like the SDK default. Only
        creation takes them: the sandbox returned from ``create`` carries the
        connection config for every later call.
        """
        return {"api_key": self.api_key, "domain": self.domain}

    async def create(
        self, config: SandboxConfig | None = None, *, from_snapshot: str | None = None
    ) -> AsyncSandbox:
        """Create a sandbox, optionally booting from a saved snapshot.

        E2B snapshots *are* templates: the id returned by ``create_snapshot()``
        is passed straight back as the template, so ``from_snapshot`` wins over
        ``config.template``. ``cpu``/``mem_mb`` are ignored because E2B sizes a
        sandbox from its template rather than at creation time.
        """
        if config is None:
            config = SandboxConfig()
        return await AsyncSandbox.create(
            template=from_snapshot or config.template,
            timeout=SANDBOX_TIMEOUT_SECONDS,
            **self._opts,
        )

    async def snapshot(self, sbx: AsyncSandbox, *, name: str | None = None) -> str:
        """Save the sandbox's current state and return the E2B snapshot id.

        The snapshot is persistent and survives sandbox deletion, so it outlives
        the ``kill`` that ends the match. Pass the returned id to ``create`` as
        ``from_snapshot`` to boot a new sandbox into the same state.
        """
        info = await sbx.create_snapshot(name)
        return info.snapshot_id

    async def kill(self, sbx: AsyncSandbox) -> None:
        await sbx.kill()

    async def exec_command(
        self, sbx: AsyncSandbox, *, command: str, user: str | None = None
    ) -> CommandResult:
        """Run an arbitrary shell command and normalize E2B's result.

        E2B raises ``CommandExitException`` on any non-zero exit while Solari
        returns the code as data. The exception carries the same stdout/stderr/
        exit code, so it is converted back into an ordinary result: callers
        decide success from ``exit_code`` instead of catching a provider error.
        """
        try:
            result = await sbx.commands.run(
                command, user=user, timeout=COMMAND_TIMEOUT_SECONDS
            )
        except CommandExitException as error:
            return CommandResult(
                exit_code=error.exit_code,
                stdout=error.stdout,
                stderr=error.stderr,
            )
        return CommandResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    async def exec_code(
        self,
        sbx: AsyncSandbox,
        *,
        code: str,
        language: str | None = None,
        context_id: str | None = None,
    ) -> None:
        """Unsupported: E2B runs code through a separate Code Interpreter SDK.

        Solari's ``run_code`` has no counterpart on a plain E2B sandbox, so this
        is kept only for interface parity with ``SolariClient``.
        """

    async def read_file(self, sbx: AsyncSandbox, *, path: str) -> str:
        return await sbx.files.read(path)

    async def write_file(
        self,
        sbx: AsyncSandbox,
        *,
        path: str,
        content: str,
        mode: int | None = None,
    ) -> None:
        """Write a file. ``mode`` is accepted for parity and ignored: the E2B
        files API sets no permission bits on write, unlike Solari's."""
        await sbx.files.write(path, content)

    async def watch_file(
        self, sbx: AsyncSandbox, *, path: str, callback: Callable[[object], None]
    ) -> Callable[[], Awaitable[None]]:
        """Watch ``path`` for changes and return an async unwatch callable.

        E2B watches directories, not individual files, so a file path is widened
        to its parent directory and events are filtered back down to that exact
        path; a directory path is watched directly. E2B delivers only the name
        relative to the watched directory, so the absolute path is rebuilt
        before the callback sees it.
        """
        try:
            is_directory = (await sbx.files.get_info(path)).type == FileType.DIR
        except FileNotFoundException:
            # A path that does not exist yet is treated as a file to watch, so
            # the parent directory is watched and filtered down to this path.
            is_directory = False

        directory = path if is_directory else (os.path.dirname(path) or "/")

        def on_event(event: FilesystemEvent) -> None:
            changed = os.path.join(directory, event.name)
            if not is_directory and changed != path:
                return
            callback(
                _FileEvent(
                    type=_EVENT_TYPES.get(event.type, "modify"),
                    path=changed,
                )
            )

        handle = await sbx.files.watch_dir(directory, on_event, recursive=is_directory)
        return handle.stop
