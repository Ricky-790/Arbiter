"""Persistence services for Arbiter's PostgreSQL tables."""

from .challenge_service import challenges_service

__all__ = [
    "challenges_service",
]
