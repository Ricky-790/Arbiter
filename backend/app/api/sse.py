"""Server-Sent Events framing shared by the streaming endpoints.

Defined once so the spectator stream and the strategy-review stream cannot
drift apart in content type, headers, or frame shape -- the frontend reads both
with the same client.
"""

from __future__ import annotations

import json
from typing import Any

SSE_MEDIA_TYPE = "text/event-stream"

#: SSE keep-alive comments keep proxies from closing an idle connection.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def frame(payload: dict[str, Any]) -> str:
    """One SSE data frame carrying a JSON payload."""
    return f"data: {json.dumps(payload)}\n\n"


def keep_alive() -> str:
    """An SSE comment, used to hold an idle connection open."""
    return ": keep-alive\n\n"
