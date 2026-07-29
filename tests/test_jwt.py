from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

from link_console_sdk import ConfigError
from link_console_sdk._internal.jwt import (
    load_ed25519_private_key,
    random_jti,
    sign_eddsa_jwt,
)


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def test_sign_produces_verifiable_jwt(ed25519_key: Ed25519PrivateKey, ed25519_pem: str) -> None:
    key = load_ed25519_private_key(ed25519_pem)
    claims = {
        "iss": "lk_client_test",
        "sub": "lk_client_test",
        "aud": "https://x",
        "jti": random_jti(),
    }
    token = sign_eddsa_jwt(key, claims)

    header_b64, payload_b64, sig_b64 = token.split(".")
    assert json.loads(_b64url_decode(header_b64)) == {"alg": "EdDSA", "typ": "JWT"}
    assert json.loads(_b64url_decode(payload_b64)) == claims

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    # Raises cryptography.exceptions.InvalidSignature if the signature is wrong.
    ed25519_key.public_key().verify(_b64url_decode(sig_b64), signing_input)


def test_header_has_no_padding(ed25519_pem: str) -> None:
    token = sign_eddsa_jwt(load_ed25519_private_key(ed25519_pem), {"a": 1})
    assert "=" not in token


def test_random_jti_unique() -> None:
    assert len({random_jti() for _ in range(100)}) == 100


def test_reject_non_ed25519_key() -> None:
    rsa_pem = generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    with pytest.raises(ConfigError, match="Ed25519"):
        load_ed25519_private_key(rsa_pem)


def test_reject_garbage_pem() -> None:
    with pytest.raises(ConfigError, match="valid PEM"):
        load_ed25519_private_key("-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----")
