"""Normalize sandbox observations and publish them to one match's Engine."""

from collections.abc import Awaitable, Callable
from typing import Any

from .models import SandboxEvent, SandboxEventType

EventHandler = Callable[[SandboxEvent], Awaitable[bool]]


class SandboxMonitor:
    def __init__(self, match_id: str, event_handler: EventHandler) -> None:
        self.match_id = match_id
        self._event_handler = event_handler

    async def publish(self, event: SandboxEvent) -> bool:
        return await self._event_handler(event)

    async def publish_file_event(self, raw_event: object) -> bool:
        raw_type = str(getattr(raw_event, "type", "file_modified")).lower()
        event_type = {
            "create": SandboxEventType.FILE_CREATED,
            "created": SandboxEventType.FILE_CREATED,
            "write": SandboxEventType.FILE_MODIFIED,
            "modify": SandboxEventType.FILE_MODIFIED,
            "modified": SandboxEventType.FILE_MODIFIED,
            "delete": SandboxEventType.FILE_DELETED,
            "deleted": SandboxEventType.FILE_DELETED,
            "access": SandboxEventType.FILE_ACCESSED,
            "accessed": SandboxEventType.FILE_ACCESSED,
        }.get(raw_type, SandboxEventType.FILE_MODIFIED)
        path = getattr(raw_event, "path", None)
        return await self.publish(
            SandboxEvent(
                type=event_type,
                path=str(path) if path is not None else None,
                metadata={"raw_type": raw_type},
            )
        )

    async def publish_process_started(self, pid: int, process: str) -> bool:
        return await self.publish(
            SandboxEvent(
                type=SandboxEventType.PROCESS_STARTED,
                process_id=pid,
                process_name=process,
            )
        )
