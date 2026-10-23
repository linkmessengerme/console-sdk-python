"""Typed, fresh user data for Login and Mini Apps, with sync/async APIs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ._internal.userinfo import AsyncUserInfoTransport, UserInfoTransport
from .errors import InvalidResponseError


@dataclass(frozen=True, slots=True, repr=False)
class UserInfo:
    sub: str
    phone_number: str | None = None
    phone_number_verified: bool | None = None


@dataclass(frozen=True, slots=True, repr=False)
class LoginUserInfo(UserInfo):
    name: str | None = None
    preferred_username: str | None = None
    picture: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class MiniAppProfile:
    name: str | None = None
    username: str | None = None
    avatar_url: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class MiniAppUserInfo(UserInfo):
    profile: MiniAppProfile | None = None


def _string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise InvalidResponseError("invalid UserInfo response")
    return value


def _common(data: dict[str, Any]) -> tuple[str, str | None, bool | None]:
    sub = data["sub"]
    assert isinstance(sub, str)  # checked by the transport
    phone = _string(data, "phone_number")
    verified = data.get("phone_number_verified")
    if (phone is not None and not re.fullmatch(r"\+[0-9]{7,15}", phone)) or (
        verified is not None and not isinstance(verified, bool)
    ):
        raise InvalidResponseError("invalid UserInfo response")
    return sub, phone, verified if phone is not None else None


def _login(data: dict[str, Any]) -> LoginUserInfo:
    sub, phone, verified = _common(data)
    return LoginUserInfo(
        sub=sub,
        phone_number=phone,
        phone_number_verified=verified,
        name=_string(data, "name"),
        preferred_username=_string(data, "preferred_username"),
        picture=_string(data, "picture"),
    )


def _miniapps(data: dict[str, Any]) -> MiniAppUserInfo:
    sub, phone, verified = _common(data)
    profile = data.get("profile")
    if profile is not None and not isinstance(profile, dict):
        raise InvalidResponseError("invalid UserInfo response")
    return MiniAppUserInfo(
        sub=sub,
        phone_number=phone,
        phone_number_verified=verified,
        profile=MiniAppProfile(
            name=_string(profile, "name"),
            username=_string(profile, "username"),
            avatar_url=_string(profile, "avatar_url"),
        )
        if profile is not None
        else None,
    )


class LoginService:
    def __init__(self, transport: UserInfoTransport) -> None:
        self._transport = transport

    def get_user_info(self, access_token: str, *, expected_sub: str | None = None) -> LoginUserInfo:
        """Read fresh data with a user token; optionally bind to a verified session subject."""
        return _login(self._transport.get("login", access_token, expected_sub))


class MiniAppsService:
    def __init__(self, transport: UserInfoTransport) -> None:
        self._transport = transport

    def get_user_info(
        self, access_token: str, *, expected_sub: str | None = None
    ) -> MiniAppUserInfo:
        """Read fresh data with the short-lived ma_ token from Mini App init."""
        return _miniapps(self._transport.get("miniapps", access_token, expected_sub))


class AsyncLoginService:
    def __init__(self, transport: AsyncUserInfoTransport) -> None:
        self._transport = transport

    async def get_user_info(
        self, access_token: str, *, expected_sub: str | None = None
    ) -> LoginUserInfo:
        return _login(await self._transport.get("login", access_token, expected_sub))


class AsyncMiniAppsService:
    def __init__(self, transport: AsyncUserInfoTransport) -> None:
        self._transport = transport

    async def get_user_info(
        self, access_token: str, *, expected_sub: str | None = None
    ) -> MiniAppUserInfo:
        return _miniapps(await self._transport.get("miniapps", access_token, expected_sub))
