from __future__ import annotations

import asyncio
import inspect
import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from link_console_sdk import (
    APIError,
    AsyncConsoleClient,
    AuthenticationError,
    ConsoleClient,
    InvalidResponseError,
    RateLimitError,
    RetryConfig,
    ValidationError,
    payments,
)

FIXTURES = json.loads((Path(__file__).parent / "fixtures/payments.json").read_text())
METHODS = {
    "CreateOrder": "create_order",
    "GetOrder": "get_order",
    "GetOrderByMerchantReference": "get_order_by_merchant_reference",
    "CancelOrder": "cancel_order",
    "RecordFulfillment": "record_fulfillment",
}


def request(name: str) -> Any:
    raw = deepcopy(FIXTURES["cases"][name]["request"])
    if name == "CreateOrder":
        raw["product"]["version"] = int(raw["product"]["version"])
        raw["product"]["kind"] = payments.ProductKind(raw["product"]["kind"])
        raw["product"] = payments.ProductSnapshot(**raw["product"])
        raw["payment"]["amount_minor"] = int(raw["payment"]["amount_minor"])
        raw["payment"] = payments.PaymentTerms(**raw["payment"])
        raw["test_outcome"] = payments.TestOutcome(raw["test_outcome"])
    if name == "RecordFulfillment":
        raw["product_version"] = int(raw["product_version"])
    return getattr(payments, name + "Request")(**raw)


async def call(client: Any, name: str, req: Any = None) -> Any:
    result = getattr(client.payments, METHODS[name])(request(name) if req is None else req)
    return await result if inspect.isawaitable(result) else result


def setup(
    key_file: str,
    asynchronous: bool,
    handler: Callable[[httpx.Request], httpx.Response],
    retry: bool = False,
) -> tuple[Any, dict[str, int], list[httpx.Request], Any]:
    scopes: dict[str, int] = {}
    requests: list[httpx.Request] = []
    lock = threading.Lock()

    def route(req: httpx.Request) -> httpx.Response:
        with lock:
            if req.url.path == "/oauth/v1/token":
                scope = parse_qs(req.content.decode())["scope"][0]
                scopes[scope] = scopes.get(scope, 0) + 1
                return httpx.Response(
                    200,
                    json={
                        "access_token": f"{scope}-{scopes[scope]}",
                        "expires_in": 900,
                    },
                )
            requests.append(req)
            return handler(req)

    http: Any = (httpx.AsyncClient if asynchronous else httpx.Client)(
        transport=httpx.MockTransport(route)
    )
    cls: Any = AsyncConsoleClient if asynchronous else ConsoleClient
    client = cls.from_credentials_json(
        key_file,
        http_client=http,
        retry=RetryConfig(max_retries=2, initial_backoff=0.001, max_backoff=0.001)
        if retry
        else False,
    )
    return client, scopes, requests, http


async def close(http: Any, asynchronous: bool) -> None:
    if asynchronous:
        await http.aclose()
    else:
        http.close()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("name", METHODS)
async def test_payment_contract(key_file: str, asynchronous: bool, name: str) -> None:
    tc = FIXTURES["cases"][name]
    client, scopes, requests, http = setup(
        key_file, asynchronous, lambda _: httpx.Response(200, json=tc["response"])
    )
    try:
        result = await call(client, name)
        assert scopes == {"payments": 1} and len(requests) == 1
        req = requests[0]
        assert req.method == "POST" and req.url.path == tc["path"]
        assert req.headers["authorization"] == "Bearer payments-1"
        assert req.headers["accept"] == req.headers["content-type"] == "application/json"
        assert json.loads(req.content) == tc["request"]
        order = result.checkout.order if name == "CreateOrder" else result.order
        assert order.product.version == 9223372036854775807
        assert order.offer.amount_minor == order.revision == 9007199254740993
        assert order.created_at == "2026-10-28T00:00:00.123456789Z"
        if name == "CreateOrder":
            assert result.checkout.method_available is False
        assert order.paid_at == tc["response"].get("order", {}).get("paid_at")
    finally:
        await close(http, asynchronous)


BUSINESS = [(name, body) for name, bodies in FIXTURES["business"].items() for body in bodies]


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("name,body", BUSINESS)
async def test_business_results(
    key_file: str,
    asynchronous: bool,
    name: str,
    body: dict[str, Any],
) -> None:
    client, _, requests, http = setup(
        key_file, asynchronous, lambda _: httpx.Response(200, json=body), retry=True
    )
    try:
        result = await call(client, name)
        assert result.result == body["result"] and len(requests) == 1
        if "order" not in body:
            assert getattr(result, "order", None) is None
        if "checkout" not in body:
            assert getattr(result, "checkout", None) is None
    finally:
        await close(http, asynchronous)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("case", FIXTURES["errors"])
async def test_proto_errors(key_file: str, asynchronous: bool, case: dict[str, Any]) -> None:
    client, _, _, http = setup(
        key_file,
        asynchronous,
        lambda _: httpx.Response(
            case["status"],
            json=case["body"],
            headers={"Retry-After": "2"},
        ),
    )
    try:
        kind = (
            AuthenticationError
            if case["status"] in (401, 403)
            else RateLimitError
            if case["status"] == 429
            else APIError
        )
        with pytest.raises(kind) as exc:
            await call(client, "GetOrder")
        error = exc.value
        assert error.code == case["body"]["code"] and error.status_code == case["status"]
        assert error.request_id == "req-payments" and error.message == case["body"]["detail"]
        assert error.details and error.details["trace_id"] == "trace-payments"
        if isinstance(error, RateLimitError):
            assert error.retry_after == "2"
            assert error.details["rate_limit"]["limit"] == "9007199254740993"
        if case["status"] == 422:
            assert error.details["field_violations"] == case["body"]["field_violations"]
    finally:
        await close(http, asynchronous)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_scopes_concurrency_and_retry(key_file: str, asynchronous: bool) -> None:
    retry_phase, attempts = False, 0
    bodies: list[bytes] = []

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if req.url.path.endswith("/otp/send"):
            assert req.headers["authorization"] == "Bearer otp-1"
            return httpx.Response(200, json={"status": "sent"})
        assert req.headers["authorization"].startswith("Bearer payments-")
        if retry_phase:
            attempts += 1
            bodies.append(req.content)
            if attempts == 1:
                return httpx.Response(503, json={"code": "ERROR_CODE_UNAVAILABLE"})
            if attempts == 2:
                return httpx.Response(401, json={"code": "ERROR_CODE_UNAUTHENTICATED"})
        return httpx.Response(200, json=FIXTURES["cases"]["CreateOrder"]["response"])

    client, scopes, _, http = setup(key_file, asynchronous, handler, retry=True)
    try:
        if asynchronous:
            await asyncio.gather(
                *[
                    call(client, "CreateOrder")
                    if i % 2
                    else client.otp.send(phone="12025550123", code="123456")
                    for i in range(12)
                ]
            )
        else:
            def sync_request(index: int) -> Any:
                if index % 2:
                    return client.payments.create_order(request("CreateOrder"))
                return client.otp.send(phone="12025550123", code="123456")

            with ThreadPoolExecutor(max_workers=12) as executor:
                list(executor.map(sync_request, range(12)))
        assert scopes == {"otp": 1, "payments": 1}
        retry_phase = True
        await call(client, "CreateOrder")
        otp = client.otp.send(phone="12025550123", code="123456")
        if inspect.isawaitable(otp):
            await otp
        assert scopes == {"otp": 1, "payments": 2}
        assert len(bodies) == 3 and len(set(bodies)) == 1
        assert json.loads(bodies[0]) == FIXTURES["cases"]["CreateOrder"]["request"]
    finally:
        await close(http, asynchronous)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("value", [True, 1.5, "100", 0, -1, 9223372036854775808])
async def test_invalid_int64_before_io(key_file: str, asynchronous: bool, value: Any) -> None:
    client, scopes, requests, http = setup(
        key_file, asynchronous, lambda _: httpx.Response(200, json={})
    )
    try:
        req = request("CreateOrder")
        req = replace(req, payment=replace(req.payment, amount_minor=value))
        with pytest.raises(ValidationError):
            await call(client, "CreateOrder", req)
        assert not scopes and not requests
    finally:
        await close(http, asynchronous)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_required_operation_and_invalid_response(key_file: str, asynchronous: bool) -> None:
    client, scopes, _, http = setup(key_file, asynchronous, lambda _: httpx.Response(200, json={}))
    try:
        for name in ("CreateOrder", "CancelOrder", "RecordFulfillment"):
            with pytest.raises(ValidationError):
                await call(client, name, replace(request(name), operation_id=""))
        assert not scopes
        with pytest.raises(InvalidResponseError):
            await call(client, "GetOrder")
    finally:
        await close(http, asynchronous)
