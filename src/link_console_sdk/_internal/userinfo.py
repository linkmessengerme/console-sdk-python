"""User-bearer HTTP, independent from OTP client_credentials and retries."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from ..errors import (
    APIError,
    AuthenticationError,
    ConfigError,
    ConnectionError,
    InvalidResponseError,
    RateLimitError,
    ValidationError,
)

Product = Literal["login", "miniapps"]
_MAX_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class UserInfoConfig:
    base_url: str
    user_agent: str
    timeout: float

    def request(self, product: Product, token: str, expected_sub: str | None) -> httpx.Request:
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 8192
            or not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token)
            or (product == "miniapps" and not re.fullmatch(r"ma_[A-Za-z0-9_-]{43}", token))
        ):
            raise ValidationError("a valid user access token is required")
        if expected_sub is not None and (
            not isinstance(expected_sub, str) or not expected_sub or len(expected_sub) > 255
        ):
            raise ValidationError("expected_sub must be a non-empty subject")
        try:
            url = urlsplit(self.base_url)
            _ = url.port  # validate port syntax before constructing the request
            local = url.hostname in ("localhost", "127.0.0.1", "::1")
            if (
                not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
                or url.path not in ("", "/")
                or any(c.isspace() or c == "\\" for c in self.base_url)
                or not (url.scheme == "https" or (url.scheme == "http" and local))
            ):
                raise ValueError
            prefix = "oauth" if product == "login" else "miniapps"
            endpoint = f"{url.scheme}://{url.netloc}/{prefix}/v1/userinfo"
        except ValueError:
            raise ConfigError(
                "UserInfo requires a trusted HTTPS API origin (HTTP only on loopback)"
            ) from None
        # A standalone Request avoids inherited cookies, default query parameters
        # and authorization headers from a supplied httpx client.
        return httpx.Request(
            "GET",
            endpoint,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Cache-Control": "no-store",
                "User-Agent": self.user_agent,
            },
            extensions={
                "timeout": httpx.Timeout(self.timeout if self.timeout > 0 else 10).as_dict()
            },
        )


def _check_response(response: httpx.Response, request: httpx.Request) -> None:
    if response.url != request.url or response.history:
        raise InvalidResponseError("unexpected UserInfo response URL")
    status = response.status_code
    if status in (401, 403):
        raise AuthenticationError(
            status_code=status,
            message="UserInfo request failed",
            code="INVALID_TOKEN" if status == 401 else "INSUFFICIENT_SCOPE",
        )
    if status == 429:
        raise RateLimitError(
            status_code=status, message="UserInfo request failed", code="TOO_MANY_REQUESTS"
        )
    if status != 200:
        raise APIError(status_code=status, message="UserInfo request failed")
    if (
        response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise InvalidResponseError("invalid UserInfo response")
    length = response.headers.get("content-length")
    if length is not None and length.isdecimal() and int(length) > _MAX_BYTES:
        raise InvalidResponseError("UserInfo response is too large")


def _decode(content: bytes, expected_sub: str | None) -> dict[str, Any]:
    try:
        data = json.loads(content.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidResponseError("invalid UserInfo response") from None
    if not isinstance(data, dict):
        raise InvalidResponseError("invalid UserInfo response")
    sub = data.get("sub")
    if (
        not isinstance(sub, str)
        or not sub
        or len(sub) > 255
        or (expected_sub is not None and sub != expected_sub)
    ):
        raise InvalidResponseError("UserInfo subject is missing or does not match")
    return data


class UserInfoTransport:
    def __init__(self, http_client: httpx.Client, config: UserInfoConfig) -> None:
        self._http = http_client
        self._config = config

    def get(self, product: Product, token: str, expected_sub: str | None) -> dict[str, Any]:
        request = self._config.request(product, token, expected_sub)
        response: httpx.Response | None = None
        try:
            response = self._http.send(request, stream=True, auth=None, follow_redirects=False)
            _check_response(response, request)
            content = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                content.extend(chunk)
                if len(content) > _MAX_BYTES:
                    raise InvalidResponseError("UserInfo response is too large")
            return _decode(bytes(content), expected_sub)
        except httpx.HTTPError:
            raise ConnectionError("UserInfo request failed") from None
        finally:
            if response is not None:
                response.close()


class AsyncUserInfoTransport:
    def __init__(self, http_client: httpx.AsyncClient, config: UserInfoConfig) -> None:
        self._http = http_client
        self._config = config

    async def get(self, product: Product, token: str, expected_sub: str | None) -> dict[str, Any]:
        request = self._config.request(product, token, expected_sub)
        response: httpx.Response | None = None
        try:
            response = await self._http.send(
                request, stream=True, auth=None, follow_redirects=False
            )
            _check_response(response, request)
            content = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=8192):
                content.extend(chunk)
                if len(content) > _MAX_BYTES:
                    raise InvalidResponseError("UserInfo response is too large")
            return _decode(bytes(content), expected_sub)
        except httpx.HTTPError:
            raise ConnectionError("UserInfo request failed") from None
        finally:
            if response is not None:
                await response.aclose()
