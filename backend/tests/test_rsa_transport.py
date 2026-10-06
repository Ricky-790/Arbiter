"""The RSA transport for api keys: key handling, decryption, and the endpoint.

Offline. The key pair is generated in-process and used the way the browser will
use it -- encrypt with the public half, send the base64 ciphertext in the same
field -- so what is pinned here is the wire contract: what the browser must
produce, what the server accepts besides it, and what it refuses.

The negative cases matter as much as the positive one. The transport has to be
invisible to every caller that has not adopted it (an existing deployment, the
README's ``curl`` flow, a client that got a 503 from the public-key endpoint),
and it must not turn a rotated key into a bogus credential that fails at the
provider with the wrong explanation.
"""

import base64
import os
import unittest
from unittest.mock import AsyncMock, patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.app import app
from app.api.routes import matches
from app.api.schemas.dto_models import ModelCheckRequest
from app.secrets import gen_rsa_keys
from app.secrets.rsa_keys import (
    PRIVATE_KEY_ENV,
    PUBLIC_KEY_ENV,
    RsaKeyError,
    decrypt_field,
    is_configured,
    public_key_jwk,
    public_key_pem,
)

PROVIDER = "openai"
MODEL = "gpt-4o-mini"


# --- helpers ----------------------------------------------------------------


def generate() -> tuple[bytes, bytes]:
    """A fresh key pair, exactly as the operator script makes one."""
    return gen_rsa_keys.generate(2048)


def env_pair(public_pem: bytes, private_pem: bytes) -> dict[str, str]:
    """The environment a deployment sets, in the form the script prints."""
    return {
        PUBLIC_KEY_ENV: base64.b64encode(public_pem).decode(),
        PRIVATE_KEY_ENV: base64.b64encode(private_pem).decode(),
    }


def encrypt(public_pem: bytes, plaintext: str) -> str:
    """What the browser does: RSA-OAEP(SHA-256), base64, same field."""
    key = serialization.load_pem_public_key(public_pem)
    ciphertext = key.encrypt(
        plaintext.encode("utf-8"),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode("ascii")


def without_keys():
    """Environment with the transport switched off."""
    return patch.dict(os.environ, {PUBLIC_KEY_ENV: "", PRIVATE_KEY_ENV: ""})


class TransportEnvMixin:
    """Sets a real key pair for the duration of a test."""

    public_pem: bytes
    private_pem: bytes

    def set_keys(self) -> None:
        self.public_pem, self.private_pem = generate()
        patcher = patch.dict(os.environ, env_pair(self.public_pem, self.private_pem))
        patcher.start()
        self.addCleanup(patcher.stop)


# --- key handling -----------------------------------------------------------


class KeyLoadingTests(TransportEnvMixin, unittest.TestCase):
    def test_a_generated_pair_round_trips_through_the_environment(self) -> None:
        self.set_keys()

        self.assertTrue(is_configured())
        self.assertIn("BEGIN PUBLIC KEY", public_key_pem())

    def test_pem_text_is_accepted_as_well_as_base64(self) -> None:
        """Operators do not all have an environment editor that likes base64."""
        public_pem, private_pem = generate()
        env = {
            PUBLIC_KEY_ENV: public_pem.decode(),
            PRIVATE_KEY_ENV: private_pem.decode(),
        }

        with patch.dict(os.environ, env):
            ciphertext = encrypt(public_pem, "sk-pem")

            self.assertEqual(decrypt_field(ciphertext), "sk-pem")

    def test_an_escaped_pem_is_unescaped(self) -> None:
        """A PEM pasted into a single-line env var carries literal backslash-n."""
        public_pem, private_pem = generate()
        env = {
            PUBLIC_KEY_ENV: public_pem.decode().replace("\n", "\\n"),
            PRIVATE_KEY_ENV: private_pem.decode().replace("\n", "\\n"),
        }

        with patch.dict(os.environ, env):
            ciphertext = encrypt(public_pem, "sk-escaped")

            self.assertEqual(decrypt_field(ciphertext), "sk-escaped")

    def test_the_public_key_is_derived_from_the_private_one(self) -> None:
        """One secret to set is one secret to get wrong."""
        public_pem, private_pem = generate()
        env = {PUBLIC_KEY_ENV: "", PRIVATE_KEY_ENV: base64.b64encode(private_pem).decode()}

        with patch.dict(os.environ, env):
            self.assertEqual(public_key_pem().strip(), public_pem.decode().strip())

    def test_the_transport_is_off_when_nothing_is_configured(self) -> None:
        with without_keys():
            self.assertFalse(is_configured())
            with self.assertRaises(RsaKeyError):
                public_key_pem()
            with self.assertRaises(RsaKeyError):
                public_key_jwk()

    def test_a_malformed_value_is_reported_rather_than_ignored(self) -> None:
        with (
            patch.dict(os.environ, {PRIVATE_KEY_ENV: "not base64 at all!!"}),
            self.assertRaises(RsaKeyError),
        ):
            decrypt_field("anything")


# --- decryption -------------------------------------------------------------


class DecryptFieldTests(TransportEnvMixin, unittest.TestCase):
    def test_a_browser_encrypted_key_comes_back_as_plaintext(self) -> None:
        self.set_keys()
        ciphertext = encrypt(self.public_pem, "sk-live-12345")

        self.assertEqual(decrypt_field(ciphertext), "sk-live-12345")

    def test_a_key_with_surrounding_whitespace_still_decrypts(self) -> None:
        self.set_keys()

        self.assertEqual(decrypt_field(f"  {encrypt(self.public_pem, 'sk-x')}  "), "sk-x")

    def test_a_plaintext_key_passes_through_when_the_transport_is_off(self) -> None:
        with without_keys():
            self.assertEqual(decrypt_field("sk-plaintext"), "sk-plaintext")

    def test_a_plaintext_key_passes_through_when_the_transport_is_on(self) -> None:
        """Every caller that has not adopted the encryption keeps working."""
        self.set_keys()

        self.assertEqual(decrypt_field("sk-plaintext"), "sk-plaintext")

    def test_a_value_the_wrong_length_is_not_treated_as_ciphertext(self) -> None:
        """Length is what makes the plaintext fallback safe, not a guess."""
        self.set_keys()
        not_our_ciphertext = base64.b64encode(b"short").decode()

        self.assertEqual(decrypt_field(not_our_ciphertext), not_our_ciphertext)

    def test_ciphertext_from_another_key_fails_loudly(self) -> None:
        """A rotated key must not silently become the API key.

        Passing it through would send ciphertext to the provider and report the
        rejection as an invalid credential -- the wrong explanation entirely.
        """
        self.set_keys()
        other_public, _ = generate()

        with self.assertRaises(RsaKeyError) as raised:
            decrypt_field(encrypt(other_public, "sk-from-another-deployment"))

        self.assertIn("could not be decrypted", str(raised.exception))


# --- the published key ------------------------------------------------------


class PublicKeyTests(TransportEnvMixin, unittest.TestCase):
    def test_the_jwk_matches_the_key_that_was_generated(self) -> None:
        self.set_keys()
        jwk = public_key_jwk()
        numbers = serialization.load_pem_public_key(self.public_pem).public_numbers()

        def b64url(value: int) -> str:
            length = (value.bit_length() + 7) // 8
            raw = base64.urlsafe_b64encode(value.to_bytes(length, "big"))
            return raw.decode().rstrip("=")

        self.assertEqual(jwk["kty"], "RSA")
        self.assertEqual(jwk["n"], b64url(numbers.n))
        self.assertEqual(jwk["e"], b64url(numbers.e))
        self.assertEqual(jwk["alg"], "RSA-OAEP-256")
        self.assertEqual(jwk["key_ops"], ["encrypt"])

    def test_the_published_pem_parses_back_to_the_same_public_key(self) -> None:
        self.set_keys()
        parsed = serialization.load_pem_public_key(public_key_pem().encode())

        self.assertEqual(
            parsed.public_numbers(),  # type: ignore[union-attr]
            serialization.load_pem_public_key(self.public_pem).public_numbers(),  # type: ignore[union-attr]
        )


class PublicKeyEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_the_endpoint_publishes_a_usable_key(self) -> None:
        public_pem, private_pem = generate()
        with patch.dict(os.environ, env_pair(public_pem, private_pem)):
            response = self.client.get("/api/v1/crypto/public-key")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["algorithm"], "RSA-OAEP")
        self.assertEqual(body["hash_algorithm"], "SHA-256")
        self.assertEqual(body["public_key_jwk"]["kty"], "RSA")
        self.assertIn("BEGIN PUBLIC KEY", body["public_key_pem"])

    def test_a_key_from_the_endpoint_encrypts_something_the_server_can_open(
        self,
    ) -> None:
        """The whole contract, end to end, with only the endpoint's answer."""
        public_pem, private_pem = generate()
        with patch.dict(os.environ, env_pair(public_pem, private_pem)):
            body = self.client.get("/api/v1/crypto/public-key").json()
            ciphertext = encrypt(body["public_key_pem"].encode(), "sk-round-trip")

            self.assertEqual(decrypt_field(ciphertext), "sk-round-trip")

    def test_an_unconfigured_deployment_says_so_rather_than_failing_oddly(
        self,
    ) -> None:
        with without_keys():
            response = self.client.get("/api/v1/crypto/public-key")

        self.assertEqual(response.status_code, 503)
        self.assertIn("ARBITER_RSA", response.json()["detail"])


# --- the fields it protects -------------------------------------------------


class ResolveSideDecryptionTests(TransportEnvMixin, unittest.IsolatedAsyncioTestCase):
    """``_resolve_side`` gates both start routes, so it decrypts there."""

    async def test_an_encrypted_key_reaches_the_provider_as_plaintext(self) -> None:
        self.set_keys()
        check = AsyncMock()

        with patch.object(matches, "check_model_exists", new=check):
            key = await matches._resolve_side(
                PROVIDER, MODEL, SecretStr(encrypt(self.public_pem, " sk-live ")), "prisoner"
            )

        self.assertEqual(key, "sk-live")
        # The provider saw the plaintext, not the ciphertext.
        check.assert_awaited_once_with(PROVIDER, MODEL, "sk-live")

    async def test_a_plaintext_key_still_works(self) -> None:
        self.set_keys()
        check = AsyncMock()

        with patch.object(matches, "check_model_exists", new=check):
            key = await matches._resolve_side(
                PROVIDER, MODEL, SecretStr(" sk-plain "), "warden"
            )

        self.assertEqual(key, "sk-plain")
        check.assert_awaited_once_with(PROVIDER, MODEL, "sk-plain")

    async def test_a_key_that_cannot_be_decrypted_is_a_400_with_the_field_name(
        self,
    ) -> None:
        self.set_keys()
        other_public, _ = generate()
        check = AsyncMock()

        with (
            patch.object(matches, "check_model_exists", new=check),
            self.assertRaises(HTTPException) as raised,
        ):
            await matches._resolve_side(
                PROVIDER,
                MODEL,
                SecretStr(encrypt(other_public, "sk-stale")),
                "prisoner",
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("prisoner_api_key", raised.exception.detail)
        check.assert_not_awaited()


class VerifyModelDecryptionTests(TransportEnvMixin, unittest.IsolatedAsyncioTestCase):
    async def test_verify_model_decrypts_before_asking_the_provider(self) -> None:
        self.set_keys()
        check = AsyncMock()

        with patch.object(matches, "check_model_exists", new=check):
            await matches.verify_model(
                ModelCheckRequest(
                    provider=PROVIDER,
                    model=MODEL,
                    api_key=SecretStr(encrypt(self.public_pem, "sk-verify")),
                )
            )

        check.assert_awaited_once_with(PROVIDER, MODEL, "sk-verify")


class GeneratorScriptTests(unittest.TestCase):
    def test_the_printed_values_load_and_work(self) -> None:
        """What the script prints has to be what the loader accepts."""
        public_pem, private_pem = generate()
        printed = {
            PUBLIC_KEY_ENV: gen_rsa_keys.encode(public_pem, as_pem=False),
            PRIVATE_KEY_ENV: gen_rsa_keys.encode(private_pem, as_pem=False),
        }

        with patch.dict(os.environ, printed):
            self.assertEqual(decrypt_field(encrypt(public_pem, "sk-printed")), "sk-printed")

    def test_pem_output_also_loads(self) -> None:
        public_pem, private_pem = generate()
        printed = {
            PUBLIC_KEY_ENV: gen_rsa_keys.encode(public_pem, as_pem=True),
            PRIVATE_KEY_ENV: gen_rsa_keys.encode(private_pem, as_pem=True),
        }

        with patch.dict(os.environ, printed):
            self.assertEqual(decrypt_field(encrypt(public_pem, "sk-pem-out")), "sk-pem-out")

    def test_the_script_prints_both_variables(self) -> None:
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = gen_rsa_keys.main(["--bits", "2048"])

        self.assertEqual(code, 0)
        printed = buffer.getvalue()
        self.assertIn(f"{PUBLIC_KEY_ENV}=", printed)
        self.assertIn(f"{PRIVATE_KEY_ENV}=", printed)

    def test_a_modulus_below_the_floor_is_refused(self) -> None:
        import contextlib
        import io

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(gen_rsa_keys.main(["--bits", "512"]), 2)


if __name__ == "__main__":
    unittest.main()
