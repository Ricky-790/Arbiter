"""Arbiter's HTTP adapter (FastAPI; thin layer over domain services)."""

from .app import app

__all__ = [
    "app",
]
