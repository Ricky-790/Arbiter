"""How an api-key field arrives over HTTP, and the one place it is unwrapped.

Every request that carries a provider key names it in the body, and a browser
encrypts that value with the deployment's public key before sending it (see
:mod:`app.api.routes.crypto`). This module is the single place that turns such a
field back into the plaintext the rest of the request handler already expected:

    plaintext key in, plaintext key out -- whether or not it was encrypted.

Keeping it in one function is what makes "decrypt only the api-key fields" a
property of the code rather than a habit: a route that reads a key through
``decrypt_api_key`` cannot forget, and nothing else in a body is ever passed to
the decryptor.
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import SecretStr

from app.secrets.rsa_keys import RsaKeyError, decrypt_field


def decrypt_api_key(secret: SecretStr | None, *, field: str) -> str | None:
    """The plaintext of one api-key field, or ``None`` when it was not sent.

    A plaintext field is returned unchanged, so a caller that has not adopted
    the encryption -- an existing deployment, the README's ``curl`` flow, a
    client that got a 503 from the public-key endpoint -- keeps working exactly
    as before.

    Raises:
        HTTPException: 400 when the value is the shape of this deployment's
            ciphertext but its private key cannot open it. That is a rotated
            key or a public key from another deployment; passing the ciphertext
            through as if it were the key would surface as a confusing provider
            rejection instead of the real problem.
    """
    if secret is None:
        return None
    try:
        return decrypt_field(secret.get_secret_value())
    except RsaKeyError as error:
        raise HTTPException(status_code=400, detail=f"{field}: {error}") from error
