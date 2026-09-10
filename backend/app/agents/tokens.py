"""Token budgets and output-limit messages shared by engine and agents.

Two tiers, both read from the environment:

- ``LOWER_TOKEN_LIMIT`` (default 4000): outputs above this are sent to the
  agent exactly once (the next turn) with a ``notice`` attached, then the
  ``output`` field is hidden while the rest of the result is kept.
- ``UPPER_TOKEN_LIMIT`` (default 10000): outputs above this are redacted
  immediately and never sent, with guidance to narrow the command.
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
    """Per-output budget for show-once-then-hide (env ``LOWER_TOKEN_LIMIT``)."""
    return _read_int("LOWER_TOKEN_LIMIT", "MAX_TOKENS", 4000)


def upper_token_limit() -> int:
    """Per-output budget for immediate redaction (env ``UPPER_TOKEN_LIMIT``)."""
    return _read_int("UPPER_TOKEN_LIMIT", None, 10000)


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


HIDDEN_OUTPUT_PLACEHOLDER = (
    "[Long Output hidden, please refer to scratchpad for important information]"
)


def lower_limit_notice(token_count: int, limit: int) -> str:
    return (
        f"This output (~{token_count} tokens) exceeds the per-output limit of "
        f"{limit} tokens and will be hidden next turn. Please use the "
        f"write_to_scratchpad tool to note any important observations now. "
        f"Next time, narrow the command first (e.g. pipe through `grep`, "
        f"`head`, or `wc`) to retrieve only what you need."
    )


def upper_limit_redaction(token_count: int, limit: int) -> str:
    return (
        f"[Output redacted immediately: ~{token_count} tokens exceeds the "
        f"upper per-output limit of {limit} tokens, so it is not shown even "
        f"once. Re-run with a narrower command (e.g. pipe through `grep`, "
        f"`head`, or `wc`) to retrieve only what you need.]"
    )


def upper_limit_notice(token_count: int, limit: int) -> str:
    return (
        f"The output (~{token_count} tokens) exceeded the upper per-output "
        f"limit of {limit} tokens and was redacted immediately. Please use "
        f"narrower commands (e.g. pipe through `grep`, `head`, or `wc`) to "
        f"retrieve only what you need, and the write_to_scratchpad tool to "
        f"note any important observations."
    )
