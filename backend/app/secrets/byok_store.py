"""Short-lived, encrypted storage for user-supplied (BYOK) provider keys.

The API and the Celery worker are separate processes, so an in-process dict
cannot carry a key between them. A key is written to Redis instead -- encrypted,
under a TTL, keyed by match and side -- and only the match id travels over the
queue, so a queued message never carries a credential.

:func:`take_api_key` reads and deletes in one step, so an entry disappears the
moment the worker builds its agents. The TTL is the backstop for a match that is
queued and never picked up.

Nothing here ever logs a key.
"""

from __future__ import annotations

import base64
import hashlib
import os
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from app.broker.redis import get_async_redis
from app.logger import get_logger

logger = get_logger()

#: Redis key namespace: one entry per match and side.
KEY_PREFIX = "arbiter:byok"

#: The two sides a match can hold a key for.
PRISONER = "prisoner"
WARDEN = "warden"

#: How long an unredeemed key survives. The worker deletes the entry as it
#: takes it, so this only bounds a match that never starts.
DEFAULT_TTL_SECONDS = 3600

#: Environment variable holding the deployment's encryption passphrase.
SECRET_ENV_VAR = "ARBITER_BYOK_SECRET"


class ByokStoreError(RuntimeError):
    """The key store could not serve a key: misconfigured or unreadable."""


def ttl_seconds() -> int:
    """Configured key lifetime, falling back to :data:`DEFAULT_TTL_SECONDS`.

    A blank or non-numeric setting is ignored rather than failing a request,
    and a non-positive value falls back too: Redis rejects ``EX 0``, which
    would otherwise leave a key with no expiry at all.
    """
    raw = os.getenv("ARBITER_BYOK_TTL_SECONDS", "")
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TTL_SECONDS
    return ttl if ttl > 0 else DEFAULT_TTL_SECONDS


def _redis_key(match_id: str | UUID, actor: str) -> str:
    return f"{KEY_PREFIX}:{match_id}:{actor}"


def _fernet() -> Fernet:
    """Fernet keyed by the deployment passphrase.

    Any non-empty passphrase works: it is hashed down to the 32 bytes Fernet
    wants, so an operator does not have to hand-generate a base64 key.
    """
    secret = os.getenv(SECRET_ENV_VAR, "")
    if not secret:
        raise ByokStoreError(
            f"{SECRET_ENV_VAR} is not set, so BYOK keys cannot be stored"
        )
    digest = hashlib.sha256(
        secret.encode("utf-8")
    ).digest()  # SHA-256: produce a fixed-size key, Base64: convert bytes into Fernet’s required format
    return Fernet(base64.urlsafe_b64encode(digest))


async def store_api_key(match_id: str | UUID, actor: str, api_key: str) -> None:
    """Encrypt one side's key and store it against the match."""
    if not api_key:
        raise ByokStoreError("Refusing to store an empty API key")
    token = (
        _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")
    )  # UTF-8 encode: converts plaintext strings into bytes for encryption. ASCII decode: converts encrypted bytes into a string for Redis.
    await get_async_redis().set(_redis_key(match_id, actor), token, ex=ttl_seconds())


async def take_api_key(match_id: str | UUID, actor: str) -> str | None:
    """Return one side's key and delete it, or ``None`` if none is stored."""
    token = await get_async_redis().getdel(_redis_key(match_id, actor))
    if token is None:
        return None
    try:
        return _fernet().decrypt(str(token).encode("ascii")).decode("utf-8")
    except InvalidToken as error:
        raise ByokStoreError(
            f"Stored key for match {match_id} could not be decrypted; "
            f"was {SECRET_ENV_VAR} rotated?"
        ) from error


async def discard_api_keys(match_id: str | UUID) -> None:
    """Drop both sides' keys for a match, whatever became of it."""
    await get_async_redis().delete(
        _redis_key(match_id, PRISONER), _redis_key(match_id, WARDEN)
    )
