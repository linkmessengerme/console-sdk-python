from __future__ import annotations

import json

import httpx
import pytest
import respx

from link_console_sdk import (
    AsyncConsoleClient,
    AuthenticationError,
    ConsoleClient,
    RateLimitError,
    ValidationError,
)

from .conftest import BASE_URL

TOKEN_URL = f"{BASE_URL}/oauth/v1/token"
SEND_URL = f"{BASE_URL}/sdk/v1/otp/send"


def _token_ok(token: str = "tok_abc") -> httpx.Response:
    body = {"access_token": token, "token_type": "Bearer", "expires_in": 3600}
    return httpx.Response(200, json=body)


def _send_ok(**extra: object) -> httpx.Response:
    body = {"request_id": "req_1", "phone": "+12025550123", "status": "sent", **extra}
    return httpx.Response(200, json=body)


@respx.mock
def test_send_ok(key_file: str) -> None:
    respx.post(TOKEN_URL).mock(return_value=_token_ok())
    send = respx.post(SEND_URL).mock(return_value=_send_ok(template_used="tpl_1", locale_used="en"))

    with ConsoleClient.from_credentials_json(key_file) as client:
        res = client.otp.send(phone="+12025550123", code="123456")

    assert (res.request_id, res.status, res.template_used, res.locale_used) == (
        "req_1",
        "sent",
        "tpl_1",
        "en",
    )
    req = send.calls.last.request
    assert req.headers["authorization"] == "Bearer tok_abc"
    assert req.headers["idempotency-key"]
    assert req.headers["content-type"] == "application/json"
    assert json.loads(req.content) == {"phone": "+12025550123", "code": "123456"}


@respx.mock
def test_locale_template_variables_in_body(key_file: str) -> None:
    respx.post(TOKEN_URL).mock(return_value=_token_ok())
    send = respx.post(SEND_URL).mock(return_value=_send_ok())

    with ConsoleClient.from_credentials_json(key_file) as client:
        client.otp.send(
            phone="12025550123",
            code="482913",
            locale="ru",
            template_id="tpl_x",
            variables={"name": "Alex"},
            idempotency_key="order-42:otp",
        )

    body = json.loads(send.calls.last.request.content)
    assert body == {
        "phone": "+12025550123",
        "code": "482913",
        "locale": "ru",
        "template_id": "tpl_x",
        "variables": {"name": "Alex"},
    }
    assert send.calls.last.request.headers["idempotency-key"] == "order-42:otp"


@respx.mock
def test_retry_on_503_then_ok(key_file: str) -> None:
    respx.post(TOKEN_URL).mock(return_value=_token_ok())
    send = respx.post(SEND_URL).mock(side_effect=[httpx.Response(503), _send_ok()])

    with ConsoleClient.from_credentials_json(key_file) as client:
        res = client.otp.send(phone="+12025550123", code="123456")

    assert res.status == "sent"
    assert send.call_count == 2


@respx.mock
def test_idempotency_conflict_in_progress_retried(key_file: str) -> None:
    respx.post(TOKEN_URL).mock(return_value=_token_ok())
    conflict = httpx.Response(
        409,
        json={"error": {"code": "IDEMPOTENCY_KEY_CONFLICT", "message": "in progress",
                        "details": {"reason": "request_in_progress"}}},
    )
    send = respx.post(SEND_URL).mock(side_effect=[conflict, _send_ok()])

    with ConsoleClient.from_credentials_json(key_file) as client:
        res = client.otp.send(phone="+12025550123", code="123456")

    assert res.status == "sent"
    assert send.call_count == 2


@respx.mock
def test_reauth_on_401(key_file: str) -> None:
    token = respx.post(TOKEN_URL).mock(side_effect=[_token_ok("tok_1"), _token_ok("tok_2")])
    unauthorized = httpx.Response(
        401, json={"error": {"code": "INVALID_TOKEN", "message": "expired"}}
    )
    send = respx.post(SEND_URL).mock(side_effect=[unauthorized, _send_ok()])

    with ConsoleClient.from_credentials_json(key_file) as client:
        res = client.otp.send(phone="+12025550123", code="123456")

    assert res.status == "sent"
    assert token.call_count == 2
    assert send.calls.last.request.headers["authorization"] == "Bearer tok_2"


@respx.mock
def test_rate_limit_error(key_file: str) -> None:
    respx.post(TOKEN_URL).mock(return_value=_token_ok())
    respx.post(SEND_URL).mock(
        return_value=httpx.Response(
            429,
            headers={"Retry-After": "5", "X-Request-Id": "rq_9"},
            json={"error": {"code": "TOO_MANY_REQUESTS", "message": "slow down"}},
        )
    )

    with (
        ConsoleClient.from_credentials_json(key_file, retry=False) as client,
        pytest.raises(RateLimitError) as excinfo,
    ):
        client.otp.send(phone="+12025550123", code="123456")

    err = excinfo.value
    assert err.status_code == 429
    assert err.retry_after == "5"
    assert err.request_id == "rq_9"


@respx.mock
def test_invalid_token_maps_to_auth_error(key_file: str) -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            401, json={"error": "invalid_client", "error_description": "bad key"}
        )
    )
    respx.post(SEND_URL).mock(return_value=_send_ok())

    with (
        ConsoleClient.from_credentials_json(key_file) as client,
        pytest.raises(AuthenticationError),
    ):
        client.otp.send(phone="+12025550123", code="123456")


def test_validation_runs_before_any_request(key_file: str) -> None:
    with respx.mock:
        token = respx.post(TOKEN_URL).mock(return_value=_token_ok())
        send = respx.post(SEND_URL).mock(return_value=_send_ok())
        with (
            ConsoleClient.from_credentials_json(key_file) as client,
            pytest.raises(ValidationError),
        ):
            client.otp.send(phone="nope", code="123456")
    assert token.call_count == 0
    assert send.call_count == 0


@respx.mock
async def test_async_send_ok(key_file: str) -> None:
    respx.post(TOKEN_URL).mock(return_value=_token_ok())
    send = respx.post(SEND_URL).mock(return_value=_send_ok())

    async with AsyncConsoleClient.from_credentials_json(key_file) as client:
        res = await client.otp.send(phone="+12025550123", code="123456")

    assert res.request_id == "req_1"
    assert send.calls.last.request.headers["authorization"] == "Bearer tok_abc"


@respx.mock
async def test_async_retry_on_503(key_file: str) -> None:
    respx.post(TOKEN_URL).mock(return_value=_token_ok())
    send = respx.post(SEND_URL).mock(side_effect=[httpx.Response(502), _send_ok()])

    async with AsyncConsoleClient.from_credentials_json(key_file) as client:
        res = await client.otp.send(phone="+12025550123", code="123456")

    assert res.status == "sent"
    assert send.call_count == 2
