"""Standalone Link Login ID-token verification and UserInfo (no private key)."""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ._internal.userinfo import AsyncUserInfoTransport, UserInfoConfig, UserInfoTransport
from ._version import VERSION
from .errors import ConfigError, LinkError
from .userinfo import AsyncLoginService, LoginService, LoginUserInfo


class IDTokenError(LinkError):
    def __init__(self) -> None:
        super().__init__("ID token validation failed")


class LoginKeySourceError(LinkError):
    def __init__(self) -> None:
        super().__init__("Login signing keys unavailable")


@dataclass(frozen=True, slots=True, repr=False)
class IDTokenClaims:
    issuer: str
    sub: str
    client_id: str
    nonce: str
    issued_at: int
    expires_at: int


def _origin(raw: str) -> str:
    try:
        u = urlsplit(raw)
        _ = u.port
        if (
            not u.hostname
            or u.username is not None
            or u.password is not None
            or u.path not in ("", "/")
            or re.search(r"[\s\\?#]", raw)
            or not (
                u.scheme == "https"
                or (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1"))
            )
        ):
            raise ValueError
        return raw.removesuffix("/")
    except (ValueError, TypeError, AttributeError):
        raise ConfigError("invalid Login configuration") from None


class _Verifier:
    def __init__(self, issuer: str, client_ids: Sequence[str], api_base_url: str | None) -> None:
        self.issuer = _origin(issuer)
        self.base = _origin(api_base_url if api_base_url is not None else issuer)
        if (
            self.issuer != issuer
            or isinstance(client_ids, str)
            or not client_ids
            or len(client_ids) > 32
            or any(
                not isinstance(v, str) or not v or len(v) > 40 or v.strip() != v for v in client_ids
            )
        ):
            raise ConfigError("invalid Login configuration")
        self.clients = frozenset(client_ids)
        self.keys: dict[str, Ed25519PublicKey] = {}
        self.expires = 0.0
        self.next_fetch = 0.0
        self.key_error: LoginKeySourceError | None = None

    def identity(self, p: dict[str, Any], nonce: str) -> IDTokenClaims:
        aud = p.get("aud")
        aud = aud if isinstance(aud, list) else [aud]
        sub, actual = p.get("sub"), p.get("nonce")
        issued, expires, nbf = p.get("iat"), p.get("exp"), p.get("nbf", 0)
        now = time.time()
        if (
            p.get("iss") != self.issuer
            or not isinstance(sub, str)
            or not sub
            or len(sub.encode()) > 255
            or len(aud) != 1
            or not isinstance(aud[0], str)
            or aud[0] not in self.clients
            or p.get("azp") != aud[0]
            or "token_use" in p
            or not isinstance(actual, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", actual)
            or not hmac.compare_digest(actual, nonce)
            or type(issued) is not int
            or type(expires) is not int
            or type(nbf) is not int
            or issued <= 0
            or expires <= issued
            or expires > 9007199254740991
            or issued > now + 30
            or expires <= now - 30
            or nbf < 0
            or nbf > now + 30
        ):
            raise IDTokenError()
        return IDTokenClaims(self.issuer, sub, aud[0], actual, issued, expires)

    def prepare(self, token: str, nonce: str) -> str:
        try:
            if (
                not isinstance(token, str)
                or len(token) > 8192
                or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token)
                or not isinstance(nonce, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", nonce)
            ):
                raise IDTokenError()
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if (
                header.get("alg") != "EdDSA"
                or header.get("typ") != "JWT"
                or not isinstance(kid, str)
                or not kid
                or len(kid) > 128
                or any(k in header for k in ("crit", "b64", "jku", "jwk", "x5u", "x5c"))
            ):
                raise IDTokenError()
            self.identity(jwt.decode(token, options={"verify_signature": False}), nonce)
            return kid
        except (jwt.PyJWTError, ValueError, TypeError, RecursionError, IDTokenError):
            raise IDTokenError() from None

    def verify(self, token: str, nonce: str, key: Ed25519PublicKey) -> IDTokenClaims:
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["EdDSA"],
                issuer=self.issuer,
                audience=list(self.clients),
                leeway=30,
                options={"require": ["iss", "sub", "aud", "azp", "iat", "exp", "nonce"]},
            )
            return self.identity(claims, nonce)
        except (jwt.PyJWTError, ValueError, TypeError, RecursionError, IDTokenError):
            raise IDTokenError() from None

    def discovery(self, data: dict[str, Any]) -> str:
        if (
            data.get("issuer") != self.issuer
            or data.get("jwks_uri") != self.base + "/oauth/v1/jwks.json"
            or not isinstance(data.get("id_token_signing_alg_values_supported"), list)
            or "EdDSA" not in data["id_token_signing_alg_values_supported"]
        ):
            raise LoginKeySourceError()
        return str(data["jwks_uri"])

    def save_keys(self, data: dict[str, Any], started: float) -> None:
        items = data.get("keys")
        if not isinstance(items, list) or not 1 <= len(items) <= 32:
            raise LoginKeySourceError()
        keys: dict[str, Ed25519PublicKey] = {}
        for k in items:
            if not isinstance(k, dict):
                raise LoginKeySourceError()
            kid, x = k.get("kid"), k.get("x")
            if (
                not isinstance(kid, str)
                or not kid
                or len(kid) > 128
                or kid in keys
                or k.get("kty") != "OKP"
                or k.get("crv") != "Ed25519"
                or k.get("alg") != "EdDSA"
                or k.get("use") != "sig"
                or "d" in k
                or not isinstance(x, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", x)
                or ("key_ops" in k and k["key_ops"] != ["verify"])
            ):
                raise LoginKeySourceError()
            raw = base64.urlsafe_b64decode(x + "=")
            if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != x:
                raise LoginKeySourceError()
            keys[kid] = Ed25519PublicKey.from_public_bytes(raw)
        self.keys = keys
        self.expires, self.next_fetch = started + 300, started + 30
        self.key_error = None

    def cached(self, kid: str) -> Ed25519PublicKey | None:
        if time.monotonic() < self.expires and kid in self.keys:
            return self.keys[kid]
        if time.monotonic() < self.next_fetch:
            raise self.key_error or IDTokenError()
        return None


def _request(url: str) -> httpx.Request:
    return httpx.Request(
        "GET",
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"link-console-sdk-python/{VERSION}",
        },
        extensions={"timeout": httpx.Timeout(5).as_dict()},
    )


def _check(response: httpx.Response, url: str) -> None:
    if (
        response.status_code != 200
        or str(response.url) != url
        or response.history
        or response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise LoginKeySourceError()
    size = response.headers.get("content-length")
    if size is not None and (not size.isdecimal() or int(size) > 65536):
        raise LoginKeySourceError()


def _decode(data: bytes | bytearray) -> dict[str, Any]:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise LoginKeySourceError()
    return value


class LoginClient:
    """Reuse per process. Trusted public config only; no app private key required."""

    def __init__(
        self,
        *,
        issuer: str,
        client_ids: Sequence[str],
        api_base_url: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._v = _Verifier(issuer, client_ids, api_base_url)
        self._http = http_client or httpx.Client(timeout=5)
        self._owns_http = http_client is None
        self._lock = threading.Lock()
        self._userinfo = LoginService(
            UserInfoTransport(
                self._http,
                UserInfoConfig(
                    self._v.base,
                    f"link-console-sdk-python/{VERSION}",
                    5,
                ),
            )
        )

    def verify_id_token(self, token: str, *, nonce: str) -> IDTokenClaims:
        """Compare the saved expected nonce; caller must atomically consume the challenge."""
        kid = self._v.prepare(token, nonce)
        with self._lock:
            key = self._v.cached(kid)
            if key is None:
                try:
                    started = time.monotonic()
                    discovery = self._json(self._v.base + "/.well-known/openid-configuration")
                    self._v.save_keys(self._json(self._v.discovery(discovery)), started)
                except (
                    httpx.HTTPError,
                    ValueError,
                    TypeError,
                    RecursionError,
                    LoginKeySourceError,
                ):
                    self._v.next_fetch = time.monotonic() + 1
                    self._v.key_error = LoginKeySourceError()
                    raise self._v.key_error from None
                key = self._v.keys.get(kid)
        if key is None:
            raise IDTokenError()
        return self._v.verify(token, nonce, key)

    def _json(self, url: str) -> dict[str, Any]:
        response = self._http.send(_request(url), stream=True, auth=None, follow_redirects=False)
        try:
            _check(response, url)
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 65536:
                    raise LoginKeySourceError()
            return _decode(content)
        finally:
            response.close()

    def get_user_info(self, access_token: str, *, expected_sub: str | None = None) -> LoginUserInfo:
        return self._userinfo.get_user_info(access_token, expected_sub=expected_sub)

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> LoginClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class AsyncLoginClient:
    """Async variant; reuse within one event loop."""

    def __init__(
        self,
        *,
        issuer: str,
        client_ids: Sequence[str],
        api_base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._v = _Verifier(issuer, client_ids, api_base_url)
        self._http = http_client or httpx.AsyncClient(timeout=5)
        self._owns_http = http_client is None
        self._lock = asyncio.Lock()
        self._userinfo = AsyncLoginService(
            AsyncUserInfoTransport(
                self._http,
                UserInfoConfig(
                    self._v.base,
                    f"link-console-sdk-python/{VERSION}",
                    5,
                ),
            )
        )

    async def verify_id_token(self, token: str, *, nonce: str) -> IDTokenClaims:
        kid = self._v.prepare(token, nonce)
        async with self._lock:
            key = self._v.cached(kid)
            if key is None:
                try:
                    await asyncio.wait_for(self._refresh(), timeout=5)
                except (
                    httpx.HTTPError,
                    ValueError,
                    TypeError,
                    RecursionError,
                    LoginKeySourceError,
                    asyncio.TimeoutError,
                ):
                    self._v.next_fetch = time.monotonic() + 1
                    self._v.key_error = LoginKeySourceError()
                    raise self._v.key_error from None
                key = self._v.keys.get(kid)
        if key is None:
            raise IDTokenError()
        return self._v.verify(token, nonce, key)

    async def _refresh(self) -> None:
        started = time.monotonic()
        discovery = await self._json(self._v.base + "/.well-known/openid-configuration")
        self._v.save_keys(await self._json(self._v.discovery(discovery)), started)

    async def _json(self, url: str) -> dict[str, Any]:
        response = await self._http.send(
            _request(url),
            stream=True,
            auth=None,
            follow_redirects=False,
        )
        try:
            _check(response, url)
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 65536:
                    raise LoginKeySourceError()
            return _decode(content)
        finally:
            await response.aclose()

    async def get_user_info(
        self,
        access_token: str,
        *,
        expected_sub: str | None = None,
    ) -> LoginUserInfo:
        return await self._userinfo.get_user_info(access_token, expected_sub=expected_sub)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncLoginClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()
