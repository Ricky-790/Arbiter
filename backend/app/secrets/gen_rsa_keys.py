"""Generate the RSA key pair the API-key transport uses, and print it.

Run it once per deployment and put the two values in the server's environment:

    uv run python -m app.secrets.gen_rsa_keys

It prints two environment-variable lines, ready to paste:

    ARBITER_RSA_PUBLIC_KEY=<base64>
    ARBITER_RSA_PRIVATE_KEY=<base64>

The public half is handed to the browser by ``GET /api/v1/crypto/public-key``;
the private half never leaves the server and is what decrypts the ``*_api_key``
fields on the way in.

Handling the private value: it is the deployment's decryption key. Anywhere it
is read by anyone else -- a shell history, a ticket, a chat message, a build log
-- the transport is compromised, so treat it like a database password and store
it as a secret, not as plain configuration. Rotating it invalidates any browser
that already fetched the old public key, which is harmless: it fetches the new
one and retries, and the previous keys stay readable only with the old private
half.

``--bits`` is 2048 by default. That is the usual floor and comfortably fits a
provider key: RSA-OAEP with SHA-256 leaves 190 bytes of payload at 2048, and 446
at 4096. The browser's encrypt step is unaffected either way.
"""

from __future__ import annotations

import argparse
import base64
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .rsa_keys import PRIVATE_KEY_ENV, PUBLIC_KEY_ENV

#: An RSA modulus must be at least this wide to be worth anything.
MIN_BITS = 2048

#: Above this the generation time stops being worth the headroom for a key that
#: is only ever asked to carry a short string.
MAX_BITS = 8192


def generate(bits: int) -> tuple[bytes, bytes]:
    """A fresh RSA key pair as PEM: ``(public, private)``."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return public_pem, private_pem


def encode(pem: bytes, *, as_pem: bool) -> str:
    """The environment value for one half.

    Base64 by default: a PEM has newlines, and a single line survives being
    pasted into a platform's environment editor or a ``.env`` file intact.
    Both forms are accepted by the loader, so ``--pem`` is available for a
    deployment that would rather set the text directly.
    """
    if as_pem:
        return pem.decode("ascii").strip()
    return base64.b64encode(pem).decode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.secrets.gen_rsa_keys",
        description="Generate the API-key transport key pair as environment values.",
    )
    parser.add_argument(
        "--bits",
        type=int,
        default=2048,
        help=f"RSA modulus size (default 2048, minimum {MIN_BITS})",
    )
    parser.add_argument(
        "--pem",
        action="store_true",
        help="print the PEM text instead of base64 (multi-line values)",
    )
    args = parser.parse_args(argv)

    if not MIN_BITS <= args.bits <= MAX_BITS:
        print(
            f"error: --bits must be between {MIN_BITS} and {MAX_BITS}",
            file=sys.stderr,
        )
        return 2

    public_pem, private_pem = generate(args.bits)

    print(f"# RSA {args.bits}-bit key pair for the API-key transport.")
    print("# Set both on every backend service; the public one is published by")
    print("# GET /api/v1/crypto/public-key. Keep the private one secret.")
    print()
    print(f"{PUBLIC_KEY_ENV}={encode(public_pem, as_pem=args.pem)}")
    print(f"{PRIVATE_KEY_ENV}={encode(private_pem, as_pem=args.pem)}")
    print()
    print("# Rotating invalidates nothing already stored: browsers re-fetch the")
    print("# public key. A browser still holding the old one gets a clear 400.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
