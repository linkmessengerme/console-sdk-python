from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BASE_URL = "https://api.example.test"


def _pem(key: Ed25519PrivateKey) -> str:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def ed25519_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def ed25519_pem(ed25519_key: Ed25519PrivateKey) -> str:
    return _pem(ed25519_key)


@pytest.fixture
def key_file(ed25519_pem: str) -> str:
    """A valid downloaded key-file, as a JSON string."""
    return json.dumps(
        {
            "type": "link_oauth_client",
            "client_id": "lk_client_test",
            "private_key": ed25519_pem,
            "api_base_url": BASE_URL,
            "environment": "test",
            "project_id": "proj_test",
        }
    )
