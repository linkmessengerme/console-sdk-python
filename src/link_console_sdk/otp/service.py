"""OTP send service (``client.otp``) — sync and async."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .._internal.idempotency import is_valid_idempotency_key, new_idempotency_key
from .._internal.transport import AsyncHttpTransport, HttpTransport
from ..errors import ValidationError
from ..validation import normalize_phone, validate_code
from .types import Locale, SendResponse

_SEND_PATH = "/sdk/v1/otp/send"


def _build_body(
    phone: str,
    code: str,
    locale: Locale | str | None,
    template_id: str | None,
    variables: Mapping[str, str] | None,
) -> dict[str, Any]:
    # Wire DTO is snake_case; the public API is keyword args.
    body: dict[str, Any] = {"phone": phone, "code": code}
    if locale is not None:
        loc = locale.value if isinstance(locale, Locale) else str(locale).strip()
        if loc:
            body["locale"] = loc
    if template_id and template_id.strip():
        body["template_id"] = template_id.strip()
    if variables:
        body["variables"] = dict(variables)
    return body


def _resolve_idempotency_key(key: str | None) -> str:
    if key is None or not key.strip():
        return new_idempotency_key()
    trimmed = key.strip()
    if not is_valid_idempotency_key(trimmed):
        raise ValidationError(
            "idempotency key must be 1-255 characters of letters, digits, "
            "underscore, dash or colon"
        )
    return trimmed


def _to_response(wire: Mapping[str, Any], phone: str) -> SendResponse:
    return SendResponse(
        request_id=str(wire.get("request_id") or ""),
        phone=str(wire.get("phone") or phone),
        status=str(wire.get("status") or ""),
        template_used=(str(wire["template_used"]) if wire.get("template_used") else None),
        locale_used=(str(wire["locale_used"]) if wire.get("locale_used") else None),
    )


class OtpService:
    """Synchronous OTP delivery API."""

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def send(
        self,
        *,
        phone: str,
        code: str,
        locale: Locale | str | None = None,
        template_id: str | None = None,
        variables: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> SendResponse:
        """Sends an OTP code to a phone via the Link bot.

        :raises ValidationError: invalid phone, code or idempotency key.
        :raises AuthenticationError: the API credentials/token were rejected.
        :raises RateLimitError: rate-limited.
        :raises APIError: any other non-2xx response.
        :raises ConnectionError: network failure, timeout or abort.
        """
        phone_e164 = normalize_phone(phone)
        validated_code = validate_code(code)
        idem = _resolve_idempotency_key(idempotency_key)
        body = _build_body(phone_e164, validated_code, locale, template_id, variables)
        wire = self._transport.do_json("POST", _SEND_PATH, body, idempotency_key=idem)
        return _to_response(wire, phone_e164)


class AsyncOtpService:
    """Asynchronous OTP delivery API."""

    def __init__(self, transport: AsyncHttpTransport) -> None:
        self._transport = transport

    async def send(
        self,
        *,
        phone: str,
        code: str,
        locale: Locale | str | None = None,
        template_id: str | None = None,
        variables: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> SendResponse:
        """Async counterpart of :meth:`OtpService.send`."""
        phone_e164 = normalize_phone(phone)
        validated_code = validate_code(code)
        idem = _resolve_idempotency_key(idempotency_key)
        body = _build_body(phone_e164, validated_code, locale, template_id, variables)
        wire = await self._transport.do_json("POST", _SEND_PATH, body, idempotency_key=idem)
        return _to_response(wire, phone_e164)
