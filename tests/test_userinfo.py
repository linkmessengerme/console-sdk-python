from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
import pytest
import respx

from link_console_sdk import (
    APIError,
    AsyncConsoleClient,
    AuthenticationError,
    ConfigError,
    ConnectionError,
    ConsoleClient,
    InvalidResponseError,
    LoginUserInfo,
    MiniAppUserInfo,
    RateLimitError,
    UserInfo,
    ValidationError,
)

from .conftest import BASE_URL

LOGIN_URL = f"{BASE_URL}/oauth/v1/userinfo"
MINI_URL = f"{BASE_URL}/miniapps/v1/userinfo"
MINI_TOKEN = "ma_" + "x" * 43
Client = ConsoleClient | AsyncConsoleClient


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def asynchronous(request: pytest.FixtureRequest) -> bool:
    return bool(request.param)


@asynccontextmanager
async def opened(key_file: str, asynchronous: bool, **options: Any) -> AsyncIterator[Client]:
    if asynchronous:
        async with AsyncConsoleClient.from_credentials_json(key_file, **options) as client:
            yield client
    else:
        with ConsoleClient.from_credentials_json(key_file, **options) as sync_client:
            yield sync_client


async def get(
    client: Client,
    product: Literal["login", "miniapps"] = "login",
    token: str = "user-token",
    expected: str | None = None,
) -> UserInfo:
    if isinstance(client, AsyncConsoleClient):
        service = client.login if product == "login" else client.mini_apps
        return await service.get_user_info(token, expected_sub=expected)
    sync_service = client.login if product == "login" else client.mini_apps
    return sync_service.get_user_info(token, expected_sub=expected)


@respx.mock
async def test_user_bearer_mapping_and_fresh_data(key_file: str, asynchronous: bool) -> None:
    login = respx.get(LOGIN_URL).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "sub": "u1",
                    "name": "Alex",
                    "preferred_username": "alex",
                    "picture": "https://img.example.test/a",
                    "phone_number": "+12025550123",
                    "phone_number_verified": False,
                },
            ),
            httpx.Response(200, json={"sub": "u1", "phone_number_verified": True}),
        ]
    )
    mini = respx.get(MINI_URL).respond(
        200,
        json={
            "sub": "u1",
            "profile": {
                "name": "Alex",
                "username": "alex",
                "avatar_url": "https://img.example.test/a",
            },
            "phone_number": "+12025550123",
        },
    )
    async with opened(key_file, asynchronous) as client:
        info = await get(client, expected="u1")
        assert isinstance(info, LoginUserInfo)
        assert (info.sub, info.name, info.preferred_username, info.picture) == (
            "u1",
            "Alex",
            "alex",
            "https://img.example.test/a",
        )
        assert info.phone_number == "+12025550123"
        assert info.phone_number_verified is False
        mini_info = await get(client, "miniapps", MINI_TOKEN, "u1")
        assert isinstance(mini_info, MiniAppUserInfo)
        assert mini_info.profile is not None
        assert mini_info.profile.avatar_url == "https://img.example.test/a"
        assert mini_info.phone_number_verified is None
        fresh = await get(client)
        assert fresh.phone_number is None and fresh.phone_number_verified is None
    for route, token in [(login, "user-token"), (mini, MINI_TOKEN)]:
        req = route.calls.last.request
        assert req.headers["authorization"] == f"Bearer {token}"
        assert req.headers["cache-control"] == "no-store"
        assert req.headers["accept"] == "application/json"
        assert "cookie" not in req.headers
        assert not req.url.query and not req.content
    assert len(respx.calls) == 3  # No app-token requests.


@pytest.mark.parametrize("status", [401, 403, 429, 503, 302])
@respx.mock
async def test_failure_is_sanitized_without_retry_or_app_auth(
    key_file: str,
    asynchronous: bool,
    status: int,
) -> None:
    route = respx.get(LOGIN_URL).respond(
        status,
        text="secret-token +12025550123",
        headers={"location": "https://other.test"},
    )
    error_type = (
        AuthenticationError
        if status in (401, 403)
        else (RateLimitError if status == 429 else APIError)
    )
    async with opened(key_file, asynchronous) as client:
        with pytest.raises(error_type) as caught:
            await get(client, token="secret-token")
    assert caught.value.status_code == status
    assert "secret-token" not in str(caught.value)
    assert "+12025550123" not in str(caught.value)
    assert caught.value.details is None
    assert route.call_count == 1 and len(respx.calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        None,
        {"sub": 123},
        {"sub": "different"},
        {"sub": "u1", "name": {}},
        {"sub": "u1", "phone_number": 123},
        {"sub": "u1", "phone_number": "12025550123"},
        {"sub": "u1", "phone_number_verified": "true"},
    ],
)
@respx.mock
async def test_invalid_response_or_wrong_subject(
    key_file: str,
    asynchronous: bool,
    body: Any,
) -> None:
    respx.get(LOGIN_URL).respond(200, json=body)
    async with opened(key_file, asynchronous) as client:
        with pytest.raises(InvalidResponseError):
            await get(client, expected="u1")


@pytest.mark.parametrize("profile", [[], {"avatar_url": 123}])
@respx.mock
async def test_invalid_mini_profile(
    key_file: str,
    asynchronous: bool,
    profile: Any,
) -> None:
    respx.get(MINI_URL).respond(200, json={"sub": "u1", "profile": profile})
    async with opened(key_file, asynchronous) as client:
        with pytest.raises(InvalidResponseError):
            await get(client, "miniapps", MINI_TOKEN)


@pytest.mark.parametrize(
    ("content", "headers"),
    [
        (b"not-json", {"content-type": "application/json"}),
        (b"[" * 2000 + b"]" * 2000, {"content-type": "application/json"}),
        (b'{"sub":"u1"}', {"content-type": "text/html"}),
        (b"\xff", {"content-type": "application/json"}),
        (b"x" * 65537, {"content-type": "application/json", "content-length": "1"}),
        (b'{"sub":"u1"}', {"content-type": "application/json", "content-length": "65537"}),
    ],
)
@respx.mock
async def test_invalid_bytes_or_size(
    key_file: str,
    asynchronous: bool,
    content: bytes,
    headers: dict[str, str],
) -> None:
    respx.get(LOGIN_URL).respond(200, content=content, headers=headers)
    async with opened(key_file, asynchronous) as client:
        with pytest.raises(InvalidResponseError):
            await get(client)


@respx.mock
async def test_validation_before_io(key_file: str, asynchronous: bool) -> None:
    async with opened(key_file, asynchronous) as client:
        for token in ["", "Bearer token", "token\r\nHeader: value", "x" * 8193]:
            with pytest.raises(ValidationError):
                await get(client, token=token)
        with pytest.raises(ValidationError):
            await get(client, "miniapps", "oauth-token")
        with pytest.raises(ValidationError):
            await get(client, expected="")
    assert not respx.calls


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.example.test",
        "https://user:password@api.example.test",
        f"{BASE_URL}/prefix",
        f"{BASE_URL}?key=secret",
        f"{BASE_URL}#fragment",
    ],
)
@respx.mock
async def test_unsafe_origin_before_io(
    key_file: str,
    asynchronous: bool,
    base_url: str,
) -> None:
    with pytest.raises(ConfigError):
        async with opened(key_file, asynchronous, base_url=base_url) as client:
            await get(client)
    assert not respx.calls


@respx.mock
async def test_regional_origin_and_no_inherited_auth_cookies_or_query(
    key_file: str,
    asynchronous: bool,
) -> None:
    regional = "https://regional-api.example.test"
    route = respx.get(f"{regional}/oauth/v1/userinfo").respond(200, json={"sub": "u1"})
    cls = httpx.AsyncClient if asynchronous else httpx.Client
    http_client = cls(
        cookies={"session": "unrelated"},
        auth=("user", "password"),
        params={"secret": "value"},
        follow_redirects=True,
    )
    try:
        async with opened(
            key_file, asynchronous, http_client=http_client, base_url=regional
        ) as sdk:
            await get(sdk)
        req = route.calls.last.request
        assert req.headers["authorization"] == "Bearer user-token"
        assert "cookie" not in req.headers
        assert not req.url.query
        assert req.extensions["timeout"]["read"] == 10
    finally:
        if isinstance(http_client, httpx.AsyncClient):
            await http_client.aclose()
        else:
            http_client.close()


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
@respx.mock
async def test_sanitized_network_error(
    key_file: str,
    asynchronous: bool,
    failure: type[httpx.HTTPError],
) -> None:
    route = respx.get(LOGIN_URL).mock(side_effect=failure("secret-token +12025550123"))
    async with opened(key_file, asynchronous) as client:
        with pytest.raises(ConnectionError) as caught:
            await get(client, token="secret-token")
    assert "secret-token" not in str(caught.value)
    assert "+12025550123" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert route.call_count == 1


@respx.mock
async def test_concurrent_users_and_otp_cache_are_independent(key_file: str) -> None:
    token = respx.post(f"{BASE_URL}/oauth/v1/token").respond(
        200,
        json={
            "access_token": "app-token",
            "token_type": "Bearer",
            "expires_in": 900,
        },
    )
    otp = respx.post(f"{BASE_URL}/sdk/v1/otp/send").respond(
        200,
        json={
            "request_id": "r1",
            "phone": "+12025550123",
            "status": "queued",
        },
    )

    async def user(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0)
        return httpx.Response(200, json={"sub": request.headers["authorization"][7:]})

    respx.get(LOGIN_URL).mock(side_effect=user)
    async with AsyncConsoleClient.from_credentials_json(key_file) as client:
        await client.otp.send(phone="+12025550123", code="123456")
        results = await asyncio.gather(
            *(client.login.get_user_info(sub, expected_sub=sub) for sub in ["alice", "bob"])
        )
        assert [info.sub for info in results] == ["alice", "bob"]
        await client.otp.send(phone="+12025550123", code="123456")
    assert token.call_count == 1
    assert all(call.request.headers["authorization"] == "Bearer app-token" for call in otp.calls)
