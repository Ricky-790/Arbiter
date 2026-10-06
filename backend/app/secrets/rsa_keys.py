"""RSA transport for the provider keys a browser sends us.

The frontend fetches the deployment's public key, encrypts each ``*_api_key``
field with RSA-OAEP(SHA-256), base64-encodes the ciphertext, and puts it back in
the same field. Nothing else in the body is touched: only those fields are
decrypted on the way in, and everything after that is unchanged.

Why asymmetric at all. The browser holds no shared secret with the server, so a
symmetric scheme would have to ship the decryption key to the browser -- and
anything that can decrypt can be read off the wire by whoever intercepts it. A
public key can be handed to anyone, and only the server holds the private half.

This is **transport only**. It protects a key on the way in. The store that
keeps it until the worker builds the agents is a separate, symmetric concern
(:mod:`app.secrets.byok_store`); one does not replace the other.

Configuring it, both from the value ``gen_rsa_keys.py`` prints::

    ARBITER_RSA_PUBLIC_KEY=<base64 of the public PEM>
    ARBITER_RSA_PRIVATE_KEY=<base64 of the private PEM>

Both accept either the base64 form or the PEM text itself (with real or
``\\n``-escaped newlines), because a platform's environment editor usually makes
one of the two awkward. Setting only the private key is enough: the public key
is derived from it.

**When the keys are not configured the transport is off**, not broken: the
public-key endpoint reports so, and fields are taken as plaintext exactly as
they were before this module existed. That keeps an existing deployment, its
tests, and the `curl` flow in the README working while a frontend adopts the
encryption.
"""

from __future__ import annotations

import base64
import binascii
import os
from functools import lru_cache

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

#: Public half, handed to the browser by ``GET /api/v1/crypto/public-key``.
PUBLIC_KEY_ENV = "ARBITER_RSA_PUBLIC_KEY"

#: Private half. Never leaves the server.
PRIVATE_KEY_ENV = "ARBITER_RSA_PRIVATE_KEY"

#: What the browser must use. WebCrypto's ``RSA-OAEP`` with ``SHA-256``.
OAEP_HASH = hashes.SHA256()
OAEP_ALGORITHM = "RSA-OAEP"
OAEP_HASH_NAME = "SHA-256"
JWK_ALGORITHM = "RSA-OAEP-256"


class RsaKeyError(Exception):
    """The RSA transport keys are missing, malformed, or did not fit."""


def _oaep() -> padding.OAEP:
    return padding.OAEP(
        mgf=padding.MGF1(algorithm=OAEP_HASH),
        algorithm=OAEP_HASH,
        label=None,
    )


def _pem_bytes(value: str, label: str) -> bytes:
    """Decode a key from its environment variable.

    Accepts base64-encoded PEM (the form ``gen_rsa_keys.py`` prints, and the
    only one that survives most environment editors) or the PEM text itself.
    """
    text = value.strip()
    if not text:
        raise RsaKeyError(f"{label} is set but empty")
    if "-----BEGIN" in text:
        # A PEM in an env var usually has its newlines escaped.
        return text.replace("\\n", "\n").encode("utf-8")
    try:
        return base64.b64decode("".join(text.split()), validate=True)
    except (binascii.Error, ValueError) as error:
        raise RsaKeyError(
            f"{label} is neither PEM text nor base64-encoded PEM"
        ) from error


@lru_cache(maxsize=8)
def _load_private(pem: bytes) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise RsaKeyError(f"{PRIVATE_KEY_ENV} is not an RSA private key")
    return key


@lru_cache(maxsize=8)
def _load_public(pem: bytes) -> rsa.RSAPublicKey:
    key = serialization.load_pem_public_key(pem)
    if not isinstance(key, rsa.RSAPublicKey):
        raise RsaKeyError(f"{PUBLIC_KEY_ENV} is not an RSA public key")
    return key


def private_key() -> rsa.RSAPrivateKey | None:
    """The configured private key, or ``None`` when the transport is off."""
    raw = os.getenv(PRIVATE_KEY_ENV, "")
    if not raw.strip():
        return None
    return _load_private(_pem_bytes(raw, PRIVATE_KEY_ENV))


def public_key() -> rsa.RSAPublicKey | None:
    """The configured public key, or ``None`` when the transport is off.

    Falls back to deriving it from the private key, so a deployment that sets
    only the private half still serves the public one.
    """
    raw = os.getenv(PUBLIC_KEY_ENV, "")
    if raw.strip():
        return _load_public(_pem_bytes(raw, PUBLIC_KEY_ENV))
    private = private_key()
    return private.public_key() if private is not None else None


def is_configured() -> bool:
    return public_key() is not None


def public_key_pem() -> str:
    """The public key as PEM text, for a non-browser client."""
    key = public_key()
    if key is None:
        raise RsaKeyError(
            f"{PUBLIC_KEY_ENV} (or {PRIVATE_KEY_ENV}) is not set, so there is "
            "no public key to publish"
        )
    return key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def _base64url(value: int) -> str:
    length = (value.bit_length() + 7) // 8
    encoded = base64.urlsafe_b64encode(value.to_bytes(length, "big"))
    return encoded.decode("ascii").rstrip("=")


def public_key_jwk() -> dict[str, object]:
    """The public key as a JWK, which WebCrypto imports directly.

    Preferred over the PEM for the browser: ``crypto.subtle.importKey`` takes a
    JWK as-is, while a PEM has to be stripped of its armour and base64-decoded
    to DER first -- a step that is easy to get subtly wrong.
    """
    key = public_key()
    if key is None:
        raise RsaKeyError(
            f"{PUBLIC_KEY_ENV} (or {PRIVATE_KEY_ENV}) is not set, so there is "
            "no public key to publish"
        )
    numbers = key.public_numbers()
    return {
        "kty": "RSA",
        "n": _base64url(numbers.n),
        "e": _base64url(numbers.e),
        "alg": JWK_ALGORITHM,
        "key_ops": ["encrypt"],
        "ext": True,
    }


def _ciphertext(value: str) -> bytes | None:
    """The value as RSA ciphertext, or ``None`` when it plainly is not one.

    The length check is what makes the plaintext fallback safe. RSA-OAEP output
    is exactly the modulus width, so a value that base64-decodes to any other
    length was never ciphertext, while one that matches is ciphertext we must
    be able to open. Without this, a rotated key would silently turn real
    ciphertext into a bogus API key and surface as a confusing provider error.
    """
    key = private_key()
    if key is None:
        return None
    try:
        decoded = base64.b64decode("".join(value.split()), validate=True)
    except (binascii.Error, ValueError):
        return None
    return decoded if len(decoded) == key.key_size // 8 else None


def decrypt_field(value: str) -> str:
    """Decrypt one api-key field, leaving a plaintext one untouched.

    Raises:
        RsaKeyError: the value is the shape of our ciphertext but the private
            key cannot open it -- a rotated key, or a public key from another
            deployment. Failing loudly is the point: treating it as plaintext
            would send the ciphertext to the provider as the key and report the
            rejection as an invalid credential.
    """
    ciphertext = _ciphertext(value)
    if ciphertext is None:
        return value
    key = private_key()
    assert key is not None  # _ciphertext only returns non-None with a key
    try:
        return key.decrypt(ciphertext, _oaep()).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise RsaKeyError(
            "The api key could not be decrypted with this deployment's private "
            "key. Fetch the public key again and re-encrypt; the server's key "
            "may have been rotated."
        ) from error


def decrypt_optional(value: str | None) -> str | None:
    """``decrypt_field`` for a field that may be absent."""
    return None if value is None else decrypt_field(value)
