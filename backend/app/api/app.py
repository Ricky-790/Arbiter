"""FastAPI application factory for Arbiter's HTTP adapter."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routes import challenges, crypto, health, matches, strategy_review

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


#: Body fields carrying a credential. FastAPI echoes the offending input back
#: in a 422, which for these would put the secret in a response body (and in
#: whatever logs it), so their value is never included.
#:
#: Matched by name pattern rather than by an explicit list: the request models
#: name the field ``prisoner_api_key`` / ``warden_api_key`` on the start routes
#: and plain ``api_key`` on ``verify-model`` and the strategy review, and a
#: hard-coded set covering only the first two silently left the third echoed.
#: Any future ``<something>_api_key`` is covered by the same rule.
SECRET_FIELD_SUFFIX = "api_key"


def is_secret_body_field(name: object) -> bool:
    """Whether one ``loc`` entry names a field carrying a credential."""
    return isinstance(name, str) and (
        name == SECRET_FIELD_SUFFIX or name.endswith(f"_{SECRET_FIELD_SUFFIX}")
    )


def scrub_secret_validation_errors(errors: list[dict]) -> list[dict]:
    """Drop the echoed value from validation errors on a credential field."""
    scrubbed: list[dict] = []
    for error in errors:
        if any(is_secret_body_field(field) for field in error.get("loc", ())):
            error = {k: v for k, v in error.items() if k not in {"input", "ctx"}}
        scrubbed.append(error)
    return scrubbed


def allowed_origins() -> list[str]:
    """Explicit CORS origins from the environment, else the dev defaults."""
    raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    configured = [origin.strip() for origin in raw.split(".") if origin.strip()]
    return configured or list(DEFAULT_CORS_ORIGINS)


app = FastAPI(title="Arbiter")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return the standard 422 with credential values removed."""
    return JSONResponse(
        status_code=422, content={"detail": scrub_secret_validation_errors(exc.errors())}
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_origin_regex=LOCALHOST_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(crypto.router)
app.include_router(challenges.router)
app.include_router(matches.router)
app.include_router(strategy_review.strategies_router)
app.include_router(strategy_review.reviewer_router)
