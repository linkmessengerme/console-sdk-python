"""OAuth-client key material, as issued by the Developer Console.

"Download key" produces a JSON file in the :class:`Credentials` shape — "in the
style of a Google service-account": the private key is revealed once, the
platform keeps only the public key. Authentication is ``private_key_jwt``: the
SDK signs a short client_assertion with this private key and exchanges it at the
token endpoint for a short-lived Bearer access token.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from ._internal.jwt import assert_ed25519_private_key
from .errors import ConfigError

OAUTH_CLIENT_TYPE = "link_oauth_client"


@dataclass
class Credentials:
    """Validated, normalized OAuth-client credentials."""

    type: str
    client_id: str
    #: PEM (PKCS#8 Ed25519) private key. Used locally to sign the client_assertion.
    private_key_pem: str
    token_url: str
    api_base_url: str
    #: Audience of the client_assertion (the Authorization Server issuer).
    issuer: str
    environment: str
    project_id: str


def _validate_url(raw: str, field: str) -> None:
    parsed = urlparse(raw.strip())
    if parsed.scheme not in ("http", "https"):
        raise ConfigError(f"credentials {field} must use http or https")
    if not parsed.netloc:
        raise ConfigError(f"credentials {field} host is required")
    if parsed.fragment:
        raise ConfigError(f"credentials {field} must not include a fragment")


def _normalize_and_validate(creds: Credentials) -> None:
    """Derives token_url/issuer from api_base_url when absent, then validates URLs."""
    _validate_url(creds.api_base_url, "api_base_url")
    base = creds.api_base_url.rstrip("/")
    if not creds.token_url:
        creds.token_url = f"{base}/oauth/v1/token"
    if not creds.issuer:
        creds.issuer = base
    _validate_url(creds.token_url, "token_url")


def from_client_key(client_id: str, private_key_pem: str, api_base_url: str) -> Credentials:
    """Builds credentials programmatically from client_id + PEM key + base URL."""
    assert_ed25519_private_key(private_key_pem)
    creds = Credentials(
        type=OAUTH_CLIENT_TYPE,
        client_id=client_id.strip(),
        private_key_pem=private_key_pem,
        token_url="",
        api_base_url=api_base_url.strip(),
        issuer="",
        environment="",
        project_id="",
    )
    if not creds.client_id:
        raise ConfigError("credentials client_id is required")
    if not creds.api_base_url:
        raise ConfigError("credentials api_base_url is required")
    _normalize_and_validate(creds)
    return creds


def from_file(file: Mapping[str, Any]) -> Credentials:
    """Builds and fully validates credentials from a parsed key-file object."""
    private_key_pem = str(file.get("private_key") or "").strip()
    assert_ed25519_private_key(private_key_pem)
    creds = Credentials(
        type=str(file.get("type") or "").strip(),
        client_id=str(file.get("client_id") or "").strip(),
        private_key_pem=private_key_pem,
        token_url=str(file.get("token_url") or "").strip(),
        api_base_url=str(file.get("api_base_url") or "").strip(),
        issuer=str(file.get("issuer") or "").strip(),
        environment=str(file.get("environment") or "").strip(),
        project_id=str(file.get("project_id") or "").strip(),
    )
    if creds.type != OAUTH_CLIENT_TYPE:
        raise ConfigError(f'credentials type must be "{OAUTH_CLIENT_TYPE}"')
    if not creds.client_id:
        raise ConfigError("credentials client_id is required")
    if not creds.api_base_url:
        raise ConfigError("credentials api_base_url is required")
    _normalize_and_validate(creds)
    return creds


def parse_credentials(data: str | bytes | Mapping[str, Any]) -> Credentials:
    """Parses credentials from a JSON string/bytes or an already-parsed mapping."""
    if isinstance(data, (str, bytes, bytearray)):
        try:
            file = json.loads(data)
        except ValueError as err:
            raise ConfigError("failed to parse credentials JSON") from err
    else:
        file = data
    if not isinstance(file, Mapping):
        raise ConfigError("credentials must be a JSON object")
    return from_file(file)
