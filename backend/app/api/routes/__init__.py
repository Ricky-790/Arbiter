"""API routers (one module per resource)."""

from . import challenges, matches, strategy_review

__all__ = [
    "challenges",
    "matches",
    "strategy_review",
]
