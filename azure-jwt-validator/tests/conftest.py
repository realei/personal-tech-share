"""Shared fixtures for validate_token tests.

Approach: generate an RSA keypair in-memory, sign test tokens locally,
and expose the public key as a fake JWKS. No network, no real Azure AD.
"""

import base64
import sys
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

# Make the script (one level up) importable as ``validate_token``.
sys.path.insert(0, str(Path(__file__).parent.parent))


TEST_KID = "test-kid"


def _b64u(data: bytes) -> str:
    """Base64url encode without padding, per RFC 7515."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _rsa_public_key_to_jwk(public_key, kid: str) -> dict:
    """Convert an RSA public key into a JWK dict."""
    numbers = public_key.public_numbers()
    n_bytes = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
    e_bytes = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _b64u(n_bytes),
        "e": _b64u(e_bytes),
    }


def _private_pem(key) -> bytes:
    """Serialize an RSA private key to PKCS8 PEM bytes."""
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture(scope="session")
def rsa_keypair():
    """Primary RSA keypair used to sign most test tokens."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def other_rsa_keypair():
    """Secondary keypair — used to produce tokens with an invalid signature."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def fake_jwks(rsa_keypair) -> dict:
    """JWKS containing only the primary public key."""
    return {"keys": [_rsa_public_key_to_jwk(rsa_keypair.public_key(), TEST_KID)]}


@pytest.fixture
def make_token(rsa_keypair):
    """Factory that returns a signed JWT with overridable claims."""

    private_pem = _private_pem(rsa_keypair)

    def _make(
        aud: str = "api://test-client",
        iss: str = "https://login.microsoftonline.com/test-tenant/v2.0",
        exp: int | None = None,
        extra: dict | None = None,
    ) -> str:
        now = int(time.time())
        payload = {
            "aud": aud,
            "iss": iss,
            "iat": now,
            "exp": exp if exp is not None else now + 3600,
            "tid": "test-tenant",
            "oid": "test-oid",
            "preferred_username": "test@example.com",
        }
        if extra:
            payload.update(extra)
        return jwt.encode(
            payload,
            private_pem,
            algorithm="RS256",
            headers={"kid": TEST_KID},
        )

    return _make


@pytest.fixture
def make_token_with_key():
    """Factory that signs a token with a caller-supplied key (for bad-sig tests)."""

    def _make(
        key,
        aud: str = "api://test-client",
        iss: str = "https://login.microsoftonline.com/test-tenant/v2.0",
    ) -> str:
        now = int(time.time())
        payload = {"aud": aud, "iss": iss, "iat": now, "exp": now + 3600}
        return jwt.encode(
            payload,
            _private_pem(key),
            algorithm="RS256",
            headers={"kid": TEST_KID},
        )

    return _make
