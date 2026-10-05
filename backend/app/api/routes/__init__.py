"""API routers (one module per resource)."""

from . import challenges, health, matches, strategy_review

__all__ = [
    "challenges",
    "health",
    "matches",
    "strategy_review",
]
