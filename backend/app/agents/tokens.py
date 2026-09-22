"""Token budget and long-output notice shared by engine and agents.

``LOWER_TOKEN_LIMIT`` (default 4000) marks an output as long. Long outputs
are always sent in full; a ``notice`` suggesting the scratchpad and narrower
commands is attached instead of hiding anything.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any


def _read_int(name: str, fallback_name: str | None, default: int) -> int:
    raw = os.getenv(name)
    if raw is None and fallback_name is not None:
        raw = os.getenv(fallback_name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def lower_token_limit() -> int:
    """Per-output budget above which output counts as long (env ``LOWER_TOKEN_LIMIT``)."""
    return _read_int("LOWER_TOKEN_LIMIT", "MAX_TOKENS", 4000)


@lru_cache(maxsize=1)
def _get_encoding() -> Any:
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def count_tokens(text: str) -> int:
    enc = _get_encoding()
    if enc is None:
        # Fallback heuristic (~4 chars/token) when tiktoken is unavailable.
        return max(1, len(text) // 4) if text else 0
    return len(enc.encode(text or ""))


def lower_limit_notice(token_count: int, limit: int) -> str:
    return (
        f"This output (~{token_count} tokens) is long (over ~{limit} tokens). "
        f"Please use the write_to_scratchpad tool to note any important "
        f"observations, and narrow future commands (e.g. pipe through `grep`, "
        f"`head`, or `wc`) to retrieve only what you need."
    )
