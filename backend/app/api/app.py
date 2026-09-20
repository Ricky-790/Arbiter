"""FastAPI application factory for Arbiter's HTTP adapter."""

from __future__ import annotations

from fastapi import FastAPI

from .routes import challenges, matches

app = FastAPI(title="Arbiter")
app.include_router(challenges.router)
app.include_router(matches.router)
