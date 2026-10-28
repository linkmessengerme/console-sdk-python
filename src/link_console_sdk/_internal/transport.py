"""HTTP transport — token attach, retries, response/error decoding.

The sync and async transports share every pure helper below; only the small
"send + retry loop" differs (blocking vs awaiting).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, cast

import httpx

from ..errors import ConnectionError, decode_api_error, is_retryable
from ..options import RetryConfig, compute_backoff
from .token import AsyncTokenSource, TokenSource

_HEADER_IDEMPOTENCY = "Idempotency-Key"
# Cap on the response body we decode, mirroring the Go/Node SDKs (1 MiB).
_MAX_RESPONSE_BYTES = 1 << 20


def _attempts(idempotency_key: str | None, retry: RetryConfig, retry_safe: bool = False) -> int:
    if (idempotency_key or retry_safe) and retry.max_retries > 0:
        return 1 + retry.max_retries
    return 1


def _request_headers(user_agent: str, token: str, idempotency_key: str | None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": user_agent,
        "Authorization": f"Bearer {token}",
    }
    if idempotency_key:
        headers[_HEADER_IDEMPOTENCY] = idempotency_key
    return headers


def _decode_response(status_code: int, headers: httpx.Headers, content: bytes) -> dict[str, Any]:
    raw = content[:_MAX_RESPONSE_BYTES] if len(content) > _MAX_RESPONSE_BYTES else content
    text = raw.decode("utf-8", errors="replace")
    if not (200 <= status_code < 300):
        raise decode_api_error(status_code, headers, text)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError as err:
        raise ConnectionError("failed to decode response body") from err
    return cast("dict[str, Any]", parsed)


def _connection_error(err: httpx.HTTPError) -> ConnectionError:
    if isinstance(err, httpx.TimeoutException):
        return ConnectionError("request timed out")
    return ConnectionError("network request failed")


class HttpTransport:
    """Synchronous transport over an :class:`httpx.Client`."""

    def __init__(
        self,
        *,
        http_client: httpx.Client,
        tokens: TokenSource,
        base_url: str,
        user_agent: str,
        retry: RetryConfig,
    ) -> None:
        self._http = http_client
        self._tokens = tokens
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._retry = retry

    def do_json(
        self,
        method: str,
        path: str,
        body: Any,
        *,
        idempotency_key: str | None = None,
        retry_safe: bool = False,
    ) -> dict[str, Any]:
        body_bytes = json.dumps(body or {}, separators=(",", ":")).encode("utf-8")
        attempts = _attempts(idempotency_key, self._retry, retry_safe)

        last_err: Exception | None = None
        for attempt in range(attempts):
            if attempt > 0:
                time.sleep(compute_backoff(attempt, self._retry))
            try:
                return self._do_once(method, path, body_bytes, idempotency_key)
            except Exception as err:  # noqa: BLE001 — re-raised unless retryable
                last_err = err
                if not is_retryable(err):
                    raise
        assert last_err is not None
        raise last_err

    def _do_once(
        self,
        method: str,
        path: str,
        body_bytes: bytes,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        token = self._tokens.get_token()
        resp = self._send(method, path, body_bytes, token, idempotency_key)
        # The token may have expired/been revoked between the proactive refresh
        # and use — re-mint once and retry (Firebase model: re-sign anytime).
        if resp.status_code == 401:
            self._tokens.invalidate()
            fresh = self._tokens.get_token()
            if fresh != token:
                resp = self._send(method, path, body_bytes, fresh, idempotency_key)
        return _decode_response(resp.status_code, resp.headers, resp.content)

    def _send(
        self,
        method: str,
        path: str,
        body_bytes: bytes,
        token: str,
        idempotency_key: str | None,
    ) -> httpx.Response:
        url = _join_url(self._base_url, path)
        headers = _request_headers(self._user_agent, token, idempotency_key)
        try:
            return self._http.request(method, url, content=body_bytes, headers=headers)
        except httpx.HTTPError as err:
            raise _connection_error(err) from err


class AsyncHttpTransport:
    """Asynchronous transport over an :class:`httpx.AsyncClient`."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        tokens: AsyncTokenSource,
        base_url: str,
        user_agent: str,
        retry: RetryConfig,
    ) -> None:
        self._http = http_client
        self._tokens = tokens
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._retry = retry

    async def do_json(
        self,
        method: str,
        path: str,
        body: Any,
        *,
        idempotency_key: str | None = None,
        retry_safe: bool = False,
    ) -> dict[str, Any]:
        body_bytes = json.dumps(body or {}, separators=(",", ":")).encode("utf-8")
        attempts = _attempts(idempotency_key, self._retry, retry_safe)

        last_err: Exception | None = None
        for attempt in range(attempts):
            if attempt > 0:
                await asyncio.sleep(compute_backoff(attempt, self._retry))
            try:
                return await self._do_once(method, path, body_bytes, idempotency_key)
            except Exception as err:  # noqa: BLE001 — re-raised unless retryable
                last_err = err
                if not is_retryable(err):
                    raise
        assert last_err is not None
        raise last_err

    async def _do_once(
        self,
        method: str,
        path: str,
        body_bytes: bytes,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        token = await self._tokens.get_token()
        resp = await self._send(method, path, body_bytes, token, idempotency_key)
        if resp.status_code == 401:
            await self._tokens.invalidate()
            fresh = await self._tokens.get_token()
            if fresh != token:
                resp = await self._send(method, path, body_bytes, fresh, idempotency_key)
        return _decode_response(resp.status_code, resp.headers, resp.content)

    async def _send(
        self,
        method: str,
        path: str,
        body_bytes: bytes,
        token: str,
        idempotency_key: str | None,
    ) -> httpx.Response:
        url = _join_url(self._base_url, path)
        headers = _request_headers(self._user_agent, token, idempotency_key)
        try:
            return await self._http.request(method, url, content=body_bytes, headers=headers)
        except httpx.HTTPError as err:
            raise _connection_error(err) from err


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url}/{path.lstrip('/')}"
