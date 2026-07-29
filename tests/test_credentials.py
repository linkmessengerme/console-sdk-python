from __future__ import annotations

import json

import pytest

from link_console_sdk import ConfigError
from link_console_sdk.credentials import from_client_key, parse_credentials


def test_parse_derives_token_url_and_issuer(key_file: str) -> None:
    creds = parse_credentials(key_file)
    assert creds.client_id == "lk_client_test"
    assert creds.api_base_url == "https://api.example.test"
    assert creds.token_url == "https://api.example.test/oauth/v1/token"
    assert creds.issuer == "https://api.example.test"


def test_parse_accepts_dict(key_file: str) -> None:
    creds = parse_credentials(json.loads(key_file))
    assert creds.project_id == "proj_test"


def test_explicit_token_url_and_issuer_preserved(ed25519_pem: str) -> None:
    data = {
        "type": "link_oauth_client",
        "client_id": "c",
        "private_key": ed25519_pem,
        "api_base_url": "https://api.example.test",
        "token_url": "https://auth.example.test/oauth/v1/token",
        "issuer": "https://issuer.example.test",
    }
    creds = parse_credentials(json.dumps(data))
    assert creds.token_url == "https://auth.example.test/oauth/v1/token"
    assert creds.issuer == "https://issuer.example.test"


def test_wrong_type_rejected(ed25519_pem: str) -> None:
    data = {"type": "nope", "client_id": "c", "private_key": ed25519_pem, "api_base_url": "https://x"}
    with pytest.raises(ConfigError, match="type"):
        parse_credentials(json.dumps(data))


def test_missing_client_id_rejected(ed25519_pem: str) -> None:
    data = {"type": "link_oauth_client", "private_key": ed25519_pem, "api_base_url": "https://x"}
    with pytest.raises(ConfigError, match="client_id"):
        parse_credentials(json.dumps(data))


def test_invalid_base_url_rejected(ed25519_pem: str) -> None:
    data = {
        "type": "link_oauth_client",
        "client_id": "c",
        "private_key": ed25519_pem,
        "api_base_url": "ftp://nope",
    }
    with pytest.raises(ConfigError, match="http or https"):
        parse_credentials(json.dumps(data))


def test_bad_json_rejected() -> None:
    with pytest.raises(ConfigError, match="parse credentials JSON"):
        parse_credentials("{not json")


def test_from_client_key_requires_base_url(ed25519_pem: str) -> None:
    creds = from_client_key("c", ed25519_pem, "https://api.example.test/")
    assert creds.api_base_url == "https://api.example.test/"
    assert creds.token_url == "https://api.example.test/oauth/v1/token"
