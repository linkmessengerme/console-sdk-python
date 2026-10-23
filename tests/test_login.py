from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from link_console_sdk import (
    AsyncLoginClient,
    ConfigError,
    IDTokenClaims,
    IDTokenError,
    InvalidResponseError,
    LoginClient,
    LoginKeySourceError,
)

ISSUER = "https://issuer.example.test"
BASE = "https://region.example.test"
NONCE = "n" * 43
Client = LoginClient | AsyncLoginClient


class Fixture:
    def __init__(self) -> None:
        self.private = Ed25519PrivateKey.generate()
        self.discovery: dict[str, Any] = {
            "issuer": ISSUER,
            "jwks_uri": BASE + "/oauth/v1/jwks.json",
            "id_token_signing_alg_values_supported": ["EdDSA"],
        }
        self.jwks: dict[str, Any] = {"keys": [self.jwk("key1")]}
        self.profile: dict[str, Any] = {
            "sub": "user1",
            "name": "Test",
            "phone_number": "+12025550123",
        }
        self.calls: list[httpx.Request] = []
        self.status = 200
        self.content: bytes | None = None

    def jwk(self, kid: str) -> dict[str, Any]:
        raw = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return {
            "kid": kid,
            "kty": "OKP",
            "crv": "Ed25519",
            "alg": "EdDSA",
            "use": "sig",
            "x": base64.urlsafe_b64encode(raw).decode().rstrip("="),
        }

    def token(
        self, claims: dict[str, Any] | None = None, header: dict[str, Any] | None = None
    ) -> str:
        now = int(time.time())
        payload = {
            "iss": ISSUER,
            "sub": "user1",
            "aud": ["ios-client"],
            "azp": "ios-client",
            "nonce": NONCE,
            "iat": now,
            "exp": now + 300,
            **(claims or {}),
        }
        return jwt.encode(
            payload, self.private, algorithm="EdDSA", headers={"kid": "key1", **(header or {})}
        )

    def request(self, r: httpx.Request) -> httpx.Response:
        self.calls.append(r)
        assert "cookie" not in r.headers
        if r.url.path.endswith("/userinfo"):
            assert str(r.url) == BASE + "/oauth/v1/userinfo"
            assert r.headers["authorization"] == "Bearer user-access"
            return httpx.Response(200, json=self.profile)
        assert "authorization" not in r.headers
        if self.content is not None:
            return httpx.Response(
                self.status, content=self.content, headers={"content-type": "application/json"}
            )
        if str(r.url) == BASE + "/.well-known/openid-configuration":
            return httpx.Response(self.status, json=self.discovery)
        assert str(r.url) == BASE + "/oauth/v1/jwks.json"
        return httpx.Response(self.status, json=self.jwks)

    @asynccontextmanager
    async def opened(self, asynchronous: bool) -> AsyncIterator[Client]:
        options: dict[str, Any] = {
            "issuer": ISSUER,
            "api_base_url": BASE,
            "client_ids": ["ios-client", "android-client"],
        }
        http_options: dict[str, Any] = {
            "transport": httpx.MockTransport(self.request),
            "auth": ("app", "secret"),
            "cookies": {"session": "secret"},
        }
        if asynchronous:
            async with (
                httpx.AsyncClient(**http_options) as http,
                AsyncLoginClient(http_client=http, **options) as client,
            ):
                yield client
        else:
            with (
                httpx.Client(**http_options) as sync_http,
                LoginClient(http_client=sync_http, **options) as sync_client,
            ):
                yield sync_client


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def asynchronous(request: pytest.FixtureRequest) -> bool:
    return bool(request.param)


async def verify(client: Client, token: str, nonce: str = NONCE) -> IDTokenClaims:
    if isinstance(client, AsyncLoginClient):
        return await client.verify_id_token(token, nonce=nonce)
    return client.verify_id_token(token, nonce=nonce)


async def test_signature_cache_concurrency_and_subject_bound_phone(asynchronous: bool) -> None:
    f = Fixture()
    async with f.opened(asynchronous) as client:
        raw = f.token()
        if isinstance(client, AsyncLoginClient):
            results = await asyncio.gather(
                *(client.verify_id_token(raw, nonce=NONCE) for _ in range(20))
            )
            profile = await client.get_user_info("user-access", expected_sub=results[0].sub)
        else:
            with ThreadPoolExecutor(8) as pool:
                results = list(
                    pool.map(lambda _: client.verify_id_token(raw, nonce=NONCE), range(20))
                )
            profile = client.get_user_info("user-access", expected_sub=results[0].sub)
        assert len(f.calls) == 3
        assert results[0].issuer == ISSUER and results[0].client_id == "ios-client"
        assert profile.phone_number == "+12025550123" and profile.phone_number_verified is None
        f.profile["sub"] = "other"
        with pytest.raises(InvalidResponseError):
            if isinstance(client, AsyncLoginClient):
                await client.get_user_info("user-access", expected_sub="user1")
            else:
                client.get_user_info("user-access", expected_sub="user1")


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://evil.test"},
        {"aud": "other"},
        {"aud": ["ios-client", "android-client"]},
        {"azp": "android-client"},
        {"azp": None},
        {"sub": ""},
        {"sub": None},
        {"nonce": "x" * 43},
        {"nonce": None},
        {"token_use": "access"},
        {"iat": 1, "exp": 2},
        {"iat": 9999999999, "exp": 10000000000},
        {"exp": None},
        {"iat": 1.5},
        {"nbf": 9999999999},
        {"iat": True},
    ],
)
async def test_invalid_claims_do_not_fetch_keys(asynchronous: bool, claims: dict[str, Any]) -> None:
    f = Fixture()
    async with f.opened(asynchronous) as client:
        with pytest.raises(IDTokenError):
            await verify(client, f.token(claims))
    assert not f.calls


@pytest.mark.parametrize(
    "header",
    [{"jku": "https://evil.test/keys"}, {"jwk": {}}, {"crit": []}, {"typ": "at+jwt"}, {"kid": ""}],
)
async def test_untrusted_headers(asynchronous: bool, header: dict[str, Any]) -> None:
    f = Fixture()
    async with f.opened(asynchronous) as client:
        with pytest.raises(IDTokenError):
            await verify(client, f.token(header=header))
    assert not f.calls


async def test_wrong_signature_and_key_rotation(asynchronous: bool) -> None:
    f = Fixture()
    async with f.opened(asynchronous) as client:
        await verify(client, f.token())
        f.private = Ed25519PrivateKey.generate()
        with pytest.raises(IDTokenError):
            await verify(client, f.token())
        f.jwks = {"keys": [f.jwk("key2")]}
        raw = f.token(header={"kid": "key2"})
        for _ in range(10):
            with pytest.raises(IDTokenError):
                await verify(client, raw)
        assert len(f.calls) == 2
        client._v.next_fetch = 0  # Simulate the end of the unknown-kid cooldown.
        await verify(client, raw)
        assert len(f.calls) == 4
        client._v.expires = client._v.next_fetch = 0
        f.status = 503
        with pytest.raises(LoginKeySourceError):
            await verify(client, raw)


@pytest.mark.parametrize(
    "mode",
    ["issuer", "jwks", "duplicate", "private", "bad-key", "oversize", "redirect", "malformed"],
)
async def test_bad_key_source(asynchronous: bool, mode: str) -> None:
    f = Fixture()
    if mode == "issuer":
        f.discovery["issuer"] = "https://evil.test"
    if mode == "jwks":
        f.discovery["jwks_uri"] = "https://evil.test/keys"
    if mode == "duplicate":
        f.jwks["keys"].append(f.jwks["keys"][0])
    if mode == "private":
        f.jwks["keys"][0]["d"] = "secret"
    if mode == "bad-key":
        f.jwks["keys"][0]["x"] = "bad"
    if mode == "oversize":
        f.content = b" " * 65537
    if mode == "redirect":
        f.status = 302
    if mode == "malformed":
        f.content = b"{"
    async with f.opened(asynchronous) as client:
        with pytest.raises(LoginKeySourceError):
            await verify(client, f.token())


async def test_invalid_input_and_algorithm(asynchronous: bool) -> None:
    f = Fixture()
    async with f.opened(asynchronous) as client:
        for raw in ["", "opaque-access", "a" * 8193, jwt.encode({}, b"x" * 32, algorithm="HS256")]:
            with pytest.raises(IDTokenError):
                await verify(client, raw)
        with pytest.raises(IDTokenError):
            await verify(client, f.token(), "")
    assert not f.calls


@pytest.mark.parametrize(
    "issuer",
    [
        "",
        "http://public.test",
        "https://user:pass@example.test",
        ISSUER + "/path",
        ISSUER + "/",
        ISSUER + "?",
    ],
)
def test_unsafe_configuration(issuer: str) -> None:
    with pytest.raises(ConfigError):
        LoginClient(issuer=issuer, client_ids=["ios-client"])
