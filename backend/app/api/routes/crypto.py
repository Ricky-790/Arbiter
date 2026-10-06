"""The public half of the API-key transport.

A browser fetches this before it sends any ``*_api_key``, encrypts just those
fields with RSA-OAEP(SHA-256), and sends the base64 ciphertext in the same
field. What the server does with it is :mod:`app.secrets.rsa_keys`.

Nothing here is secret: a public key is meant to be handed out. That is the
whole reason the transport is asymmetric -- anything the browser could use to
*decrypt* would have to be readable by whoever intercepts the request.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas.dto_models import PublicKeyResponse
from app.secrets.rsa_keys import (
    OAEP_ALGORITHM,
    OAEP_HASH_NAME,
    RsaKeyError,
    public_key_jwk,
    public_key_pem,
)

router = APIRouter(prefix="/api/v1/crypto", tags=["crypto"])


@router.get("/public-key", response_model=PublicKeyResponse)
async def get_public_key() -> PublicKeyResponse:
    """The key a browser encrypts its api-key fields with.

    A 503 means this deployment has not configured the transport
    (``ARBITER_RSA_PUBLIC_KEY`` / ``ARBITER_RSA_PRIVATE_KEY``), not that it is
    down. A client that sees it should send those fields as plaintext, which
    the server still accepts.
    """
    try:
        return PublicKeyResponse(
            algorithm=OAEP_ALGORITHM,
            hash_algorithm=OAEP_HASH_NAME,
            public_key_jwk=public_key_jwk(),
            public_key_pem=public_key_pem(),
        )
    except RsaKeyError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
