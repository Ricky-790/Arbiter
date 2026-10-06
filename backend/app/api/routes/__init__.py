"""API routers (one module per resource)."""

from . import challenges, crypto, health, matches, strategy_review

__all__ = [
    "challenges",
    "crypto",
    "health",
    "matches",
    "strategy_review",
]
