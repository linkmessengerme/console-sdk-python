"""Error taxonomy.

- :class:`ConfigError` / :class:`ValidationError` — raised locally, before any
  request leaves the process (bad credentials, options, phone, code).
- :class:`APIError` and its subclasses — the gateway returned a non-2xx
  response. :class:`AuthenticationError`, :class:`IdempotencyError` and
  :class:`RateLimitError` are specializations keyed off the error code.
- :class:`ConnectionError` — the request never produced an HTTP response
  (network failure, timeout, abort).

Every error extends :class:`LinkError`, so ``except LinkError`` captures
everything this SDK raises.

.. note::
   ``ConnectionError`` intentionally shadows the built-in of the same name
   *inside this package's namespace* — it is the SDK's network-failure type,
   matching the Go/Node SDKs. Import it explicitly from ``link_console_sdk``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

# Error codes the gateway returns in the ``error.code`` envelope field.
CODE_INVALID_TOKEN = "INVALID_TOKEN"
CODE_INSUFFICIENT_SCOPE = "INSUFFICIENT_SCOPE"
CODE_IDEMPOTENCY_KEY_CONFLICT = "IDEMPOTENCY_KEY_CONFLICT"
CODE_TOO_MANY_REQUESTS = "TOO_MANY_REQUESTS"


class LinkError(Exception):
    """Base class for every error raised by the SDK."""


class ConfigError(LinkError):
    """Invalid credentials or client configuration."""


class ValidationError(LinkError):
    """Invalid request input, including user tokens (raised before I/O)."""


class InvalidResponseError(LinkError):
    """Invalid UserInfo JSON, schema, size or subject; excludes raw response data."""


class ConnectionError(LinkError):  # noqa: A001 — deliberate parity with Go/Node SDKs
    """The request failed before an HTTP response (network error, timeout, abort)."""


class APIError(LinkError):
    """The gateway returned a non-2xx HTTP status."""

    def __init__(
        self,
        *,
        status_code: int,
        message: str,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(_format_api_message(status_code, code, message))
        self.status_code = status_code
        self.message = message
        self.code = code
        self.details: dict[str, Any] | None = dict(details) if details is not None else None
        #: Value of the ``X-Request-Id`` response header, when present.
        self.request_id = request_id


class AuthenticationError(APIError):
    """Bearer token rejected (``INVALID_TOKEN``, ``INSUFFICIENT_SCOPE``)."""


class IdempotencyError(APIError):
    """Idempotency key reused with a different payload (``IDEMPOTENCY_KEY_CONFLICT``)."""


class RateLimitError(APIError):
    """Rate limit exceeded (``TOO_MANY_REQUESTS``)."""

    def __init__(self, *, retry_after: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        #: Raw ``Retry-After`` header value, if the gateway provided one.
        self.retry_after = retry_after


def _format_api_message(status_code: int, code: str | None, message: str) -> str:
    if not code:
        return f"link: API error ({status_code}): {message}"
    return f"link: API error {code} ({status_code}): {message}"


def http_status_text(status_code: int) -> str:
    """Human-readable reason phrase for a status code (falls back to ``HTTP <n>``)."""
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return f"HTTP {status_code}"


def decode_api_error(
    status_code: int,
    headers: Mapping[str, str],
    body_text: str,
) -> APIError:
    """Maps a non-2xx gateway response into the matching typed :class:`APIError`."""
    request_id = headers.get("x-request-id")
    code: str | None = None
    message = http_status_text(status_code)
    details: dict[str, Any] | None = None

    if body_text:
        try:
            envelope = json.loads(body_text)
        except ValueError:
            envelope = None
        if isinstance(envelope, dict):
            err = envelope.get("error")
            if isinstance(err, dict) and err.get("code"):
                code = str(err["code"])
                message = str(err.get("message") or message)
                raw_details = err.get("details")
                if isinstance(raw_details, dict):
                    details = raw_details

    init: dict[str, Any] = {
        "status_code": status_code,
        "code": code,
        "message": message,
        "details": details,
        "request_id": request_id,
    }
    if code in (CODE_INVALID_TOKEN, CODE_INSUFFICIENT_SCOPE):
        return AuthenticationError(**init)
    if code == CODE_IDEMPOTENCY_KEY_CONFLICT:
        return IdempotencyError(**init)
    if code == CODE_TOO_MANY_REQUESTS:
        return RateLimitError(retry_after=headers.get("retry-after"), **init)
    return APIError(**init)


def is_retryable(err: Exception) -> bool:
    """Whether a failed attempt may be safely retried (idempotent requests only)."""
    if isinstance(err, ConnectionError):
        return True
    if isinstance(err, APIError):
        if err.status_code in (408, 429, 500, 502, 503, 504):
            return True
        if err.status_code == 409:
            return (
                err.code == CODE_IDEMPOTENCY_KEY_CONFLICT
                and (err.details or {}).get("reason") == "request_in_progress"
            )
    return False


# Convenience predicates (``isinstance`` works too; these mirror the Node guards).
def is_link_error(err: object) -> bool:
    return isinstance(err, LinkError)


def is_api_error(err: object) -> bool:
    return isinstance(err, APIError)


def is_authentication_error(err: object) -> bool:
    return isinstance(err, AuthenticationError)


def is_idempotency_error(err: object) -> bool:
    return isinstance(err, IdempotencyError)


def is_rate_limit_error(err: object) -> bool:
    return isinstance(err, RateLimitError)


def is_connection_error(err: object) -> bool:
    return isinstance(err, ConnectionError)


def is_validation_error(err: object) -> bool:
    return isinstance(err, ValidationError)
