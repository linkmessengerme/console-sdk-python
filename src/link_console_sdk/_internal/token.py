"""App access-token minting via OAuth2 ``client_credentials`` + ``private_key_jwt``.

The SDK mints a short-lived client_assertion (signed with the Ed25519 key),
exchanges it at the token endpoint for an app access token, and caches that token
until it expires. This is the Firebase Admin SDK model: the private key stays on
the backend, so a fresh token can be minted at any time — no refresh token.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from ..errors import APIError, AuthenticationError, ConnectionError, http_status_text
from .jwt import load_ed25519_private_key, random_jti, sign_eddsa_jwt

_GRANT = "client_credentials"
_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
_ASSERTION_TTL = 300  # seconds
_EXPIRY_SKEW = 30  # seconds


def _now_unix() -> int:
    return int(time.time())


def _build_form(assertion: str, client_id: str, scope: str) -> dict[str, str]:
    form = {
        "grant_type": _GRANT,
        "client_assertion_type": _ASSERTION_TYPE,
        "client_assertion": assertion,
        "client_id": client_id,
    }
    if scope:
        form["scope"] = scope
    return form


def _parse_token_response(
    status_code: int,
    headers: Mapping[str, str],
    text: str,
    now: int,
) -> tuple[str, int]:
    """Returns ``(access_token, expiry_unix)`` or raises the mapped SDK error."""
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}

    if not (200 <= status_code < 300):
        raise _token_error(status_code, parsed, headers)

    token = parsed.get("access_token")
    if not token:
        raise AuthenticationError(
            status_code=status_code,
            message="token endpoint returned no access_token",
        )
    try:
        ttl = int(parsed.get("expires_in") or 0)
    except (TypeError, ValueError):
        ttl = 0
    expiry = now + max(0, ttl - _EXPIRY_SKEW)
    return str(token), expiry


def _token_error(
    status_code: int, parsed: Mapping[str, Any], headers: Mapping[str, str]
) -> Exception:
    """5xx/408/429 → retryable :class:`APIError`; 4xx → :class:`AuthenticationError`."""
    error = parsed.get("error")
    message = str(parsed.get("error_description") or error or http_status_text(status_code))
    init: dict[str, Any] = {
        "status_code": status_code,
        "code": str(error).upper() if error else None,
        "message": message,
        "request_id": headers.get("x-request-id"),
    }
    if status_code >= 500 or status_code in (408, 429):
        return APIError(**init)
    return AuthenticationError(**init)


class TokenSource:
    """Synchronous token cache backed by an :class:`httpx.Client`."""

    def __init__(
        self,
        *,
        http_client: httpx.Client,
        token_url: str,
        client_id: str,
        issuer: str,
        private_key_pem: str,
        scope: str,
        user_agent: str,
        now: Callable[[], int] | None = None,
    ) -> None:
        self._http = http_client
        self._token_url = token_url
        self._client_id = client_id
        self._issuer = issuer
        self._key = load_ed25519_private_key(private_key_pem)
        self._scope = scope
        self._user_agent = user_agent
        self._now = now or _now_unix
        self._lock = threading.Lock()
        self._token = ""
        self._expiry = 0

    def get_token(self) -> str:
        # Serializing refreshes under the lock also dedupes a burst of concurrent
        # callers into a single mint (the losers see the freshly-cached token).
        with self._lock:
            now = self._now()
            if self._token and now < self._expiry:
                return self._token
            return self._refresh(now)

    def invalidate(self) -> None:
        with self._lock:
            self._token = ""
            self._expiry = 0

    def _refresh(self, now: int) -> str:
        assertion = sign_eddsa_jwt(self._key, _assertion_claims(self._client_id, self._issuer, now))
        form = _build_form(assertion, self._client_id, self._scope)
        try:
            resp = self._http.post(
                self._token_url,
                data=form,
                headers={"Accept": "application/json", "User-Agent": self._user_agent},
            )
        except httpx.HTTPError as err:
            raise ConnectionError("token request failed") from err
        token, expiry = _parse_token_response(resp.status_code, resp.headers, resp.text, now)
        self._token, self._expiry = token, expiry
        return token


class AsyncTokenSource:
    """Asynchronous token cache backed by an :class:`httpx.AsyncClient`."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        token_url: str,
        client_id: str,
        issuer: str,
        private_key_pem: str,
        scope: str,
        user_agent: str,
        now: Callable[[], int] | None = None,
    ) -> None:
        self._http = http_client
        self._token_url = token_url
        self._client_id = client_id
        self._issuer = issuer
        self._key = load_ed25519_private_key(private_key_pem)
        self._scope = scope
        self._user_agent = user_agent
        self._now = now or _now_unix
        self._lock = asyncio.Lock()
        self._token = ""
        self._expiry = 0

    async def get_token(self) -> str:
        async with self._lock:
            now = self._now()
            if self._token and now < self._expiry:
                return self._token
            return await self._refresh(now)

    async def invalidate(self) -> None:
        async with self._lock:
            self._token = ""
            self._expiry = 0

    async def _refresh(self, now: int) -> str:
        assertion = sign_eddsa_jwt(self._key, _assertion_claims(self._client_id, self._issuer, now))
        form = _build_form(assertion, self._client_id, self._scope)
        try:
            resp = await self._http.post(
                self._token_url,
                data=form,
                headers={"Accept": "application/json", "User-Agent": self._user_agent},
            )
        except httpx.HTTPError as err:
            raise ConnectionError("token request failed") from err
        token, expiry = _parse_token_response(resp.status_code, resp.headers, resp.text, now)
        self._token, self._expiry = token, expiry
        return token


def _assertion_claims(client_id: str, issuer: str, now: int) -> dict[str, Any]:
    return {
        "iss": client_id,
        "sub": client_id,
        "aud": issuer,
        "iat": now,
        "exp": now + _ASSERTION_TTL,
        "jti": random_jti(),
    }
