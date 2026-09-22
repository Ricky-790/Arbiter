"""FastAPI application factory for Arbiter's HTTP adapter."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import challenges, matches

load_dotenv()

#: Browser origins allowed to call the API during local development.
#: Override in production with a comma-separated ``CORS_ALLOW_ORIGINS``.
DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
)

#: Any localhost port, so the frontend dev server keeps working even when it
#: falls back to a different port.
LOCALHOST_ORIGIN_REGEX = r"http://(localhost|127\.0\.0\.1)(:\d+)?"


def allowed_origins() -> list[str]:
    """Explicit CORS origins from the environment, else the dev defaults."""
    raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    configured = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return configured or list(DEFAULT_CORS_ORIGINS)


app = FastAPI(title="Arbiter")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_origin_regex=LOCALHOST_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(challenges.router)
app.include_router(matches.router)
