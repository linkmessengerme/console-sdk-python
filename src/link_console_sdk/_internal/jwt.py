"""EdDSA (Ed25519) client-assertion JWT signing.

The header/payload/signature are assembled by hand rather than pulling in a JWT
library — the only third-party dependency here is ``cryptography`` for Ed25519,
which the Python standard library does not provide.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from typing import Any

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from ..errors import ConfigError

# Compact, fixed header — no ``kid`` (the client_assertion is verified against
# the client's registered public key). Byte-identical to the Go/Node SDKs.
_HEADER = b'{"alg":"EdDSA","typ":"JWT"}'


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def load_ed25519_private_key(pem: str) -> Ed25519PrivateKey:
    """Parses + validates a PEM Ed25519 private key (raises :class:`ConfigError`)."""
    try:
        key = load_pem_private_key(pem.encode("utf-8"), password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm) as err:
        raise ConfigError("credentials private_key is not valid PEM") from err
    if not isinstance(key, Ed25519PrivateKey):
        raise ConfigError("credentials private_key must be an Ed25519 key")
    return key


def assert_ed25519_private_key(pem: str) -> None:
    """Fail-fast validation at credential load (does not retain the key)."""
    load_ed25519_private_key(pem)


def sign_eddsa_jwt(key: Ed25519PrivateKey, claims: Mapping[str, Any]) -> str:
    """Signs a compact EdDSA JWT: ``base64url(header).base64url(claims).base64url(sig)``."""
    header = _b64url(_HEADER)
    payload = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header}.{payload}"
    signature = key.sign(signing_input.encode("ascii"))
    return f"{signing_input}.{_b64url(signature)}"


def random_jti() -> str:
    """A fresh JWT id — 16 random bytes, base64url (no padding)."""
    return _b64url(os.urandom(16))
