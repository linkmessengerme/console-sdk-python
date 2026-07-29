"""Entry points for the Link Console API — sync :class:`ConsoleClient` and
async :class:`AsyncConsoleClient`."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from ._internal.token import AsyncTokenSource, TokenSource
from ._internal.transport import AsyncHttpTransport, HttpTransport
from .credentials import Credentials, from_client_key, parse_credentials
from .errors import ConfigError
from .options import DEFAULT_TIMEOUT, RetryConfig, resolve_retry, resolve_user_agent
from .otp.service import AsyncOtpService, OtpService

# The SDK only serves OTP; the app token is requested with this scope.
_SCOPE_OTP = "otp"


def _normalize_base_url(url: str | None) -> str | None:
    if not url:
        return None
    trimmed = url.strip().rstrip("/")
    return trimmed or None


def _resolve_credentials(
    client_id: str,
    private_key: str,
    base_url: str | None,
    token_url: str | None,
    issuer: str | None,
) -> Credentials:
    base = _normalize_base_url(base_url)
    if not base:
        raise ConfigError(
            "base_url is required — use ConsoleClient.from_key_file / "
            "from_credentials_json, or pass the api_base_url from your key"
        )
    creds = from_client_key(client_id, private_key, base)
    if token_url and token_url.strip():
        creds.token_url = token_url.strip()
    if issuer and issuer.strip():
        creds.issuer = issuer.strip()
    return creds


def _credentials_json_kwargs(
    data: str | bytes | Mapping[str, Any],
    base_url_override: str | None,
) -> dict[str, Any]:
    """Turns a key-file into constructor kwargs, honoring a base_url override."""
    creds = parse_credentials(data)
    override = _normalize_base_url(base_url_override)
    base = override or creds.api_base_url
    # An override changes where requests go (api_base_url + token_url); the issuer
    # (token audience = the AS identity) stays from the key-file.
    token_url = f"{base.rstrip('/')}/oauth/v1/token" if override else creds.token_url
    return {
        "client_id": creds.client_id,
        "private_key": creds.private_key_pem,
        "base_url": base,
        "token_url": token_url,
        "issuer": creds.issuer,
    }


class ConsoleClient:
    """Synchronous client for the Link Console API.

    .. code-block:: python

        client = ConsoleClient.from_key_file("link-oauth-client.json")
        res = client.otp.send(phone="+12025550123", code="123456")
        client.close()

    Use it as a context manager to close the underlying HTTP client
    automatically::

        with ConsoleClient.from_key_file("key.json") as client:
            client.otp.send(phone="+12025550123", code="123456")
    """

    def __init__(
        self,
        *,
        client_id: str,
        private_key: str,
        base_url: str,
        token_url: str | None = None,
        issuer: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry: RetryConfig | bool | None = None,
        user_agent_suffix: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        creds = _resolve_credentials(client_id, private_key, base_url, token_url, issuer)
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)
        user_agent = resolve_user_agent(user_agent_suffix)
        tokens = TokenSource(
            http_client=self._http,
            token_url=creds.token_url,
            client_id=creds.client_id,
            issuer=creds.issuer,
            private_key_pem=creds.private_key_pem,
            scope=_SCOPE_OTP,
            user_agent=user_agent,
        )
        transport = HttpTransport(
            http_client=self._http,
            tokens=tokens,
            base_url=creds.api_base_url,
            user_agent=user_agent,
            retry=resolve_retry(retry),
        )
        #: OTP delivery API.
        self.otp = OtpService(transport)

    @classmethod
    def from_key_file(cls, path: str | Path, **options: Any) -> ConsoleClient:
        """Loads credentials from a downloaded key file (``*.json``)."""
        try:
            data = Path(path).read_text(encoding="utf-8")
        except OSError as err:
            raise ConfigError(f"failed to read credentials file: {path}") from err
        return cls.from_credentials_json(data, **options)

    @classmethod
    def from_credentials_json(
        cls,
        data: str | bytes | Mapping[str, Any],
        *,
        base_url: str | None = None,
        **options: Any,
    ) -> ConsoleClient:
        """Builds a client from key-file JSON (string/bytes or parsed mapping)."""
        return cls(**_credentials_json_kwargs(data, base_url), **options)

    def close(self) -> None:
        """Closes the underlying HTTP client (unless one was supplied)."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> ConsoleClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class AsyncConsoleClient:
    """Asynchronous client for the Link Console API.

    .. code-block:: python

        async with AsyncConsoleClient.from_key_file("key.json") as client:
            res = await client.otp.send(phone="+12025550123", code="123456")
    """

    def __init__(
        self,
        *,
        client_id: str,
        private_key: str,
        base_url: str,
        token_url: str | None = None,
        issuer: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry: RetryConfig | bool | None = None,
        user_agent_suffix: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        creds = _resolve_credentials(client_id, private_key, base_url, token_url, issuer)
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        user_agent = resolve_user_agent(user_agent_suffix)
        tokens = AsyncTokenSource(
            http_client=self._http,
            token_url=creds.token_url,
            client_id=creds.client_id,
            issuer=creds.issuer,
            private_key_pem=creds.private_key_pem,
            scope=_SCOPE_OTP,
            user_agent=user_agent,
        )
        transport = AsyncHttpTransport(
            http_client=self._http,
            tokens=tokens,
            base_url=creds.api_base_url,
            user_agent=user_agent,
            retry=resolve_retry(retry),
        )
        #: OTP delivery API.
        self.otp = AsyncOtpService(transport)

    @classmethod
    def from_key_file(cls, path: str | Path, **options: Any) -> AsyncConsoleClient:
        """Loads credentials from a downloaded key file (``*.json``)."""
        try:
            data = Path(path).read_text(encoding="utf-8")
        except OSError as err:
            raise ConfigError(f"failed to read credentials file: {path}") from err
        return cls.from_credentials_json(data, **options)

    @classmethod
    def from_credentials_json(
        cls,
        data: str | bytes | Mapping[str, Any],
        *,
        base_url: str | None = None,
        **options: Any,
    ) -> AsyncConsoleClient:
        """Builds a client from key-file JSON (string/bytes or parsed mapping)."""
        return cls(**_credentials_json_kwargs(data, base_url), **options)

    async def aclose(self) -> None:
        """Closes the underlying HTTP client (unless one was supplied)."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncConsoleClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
