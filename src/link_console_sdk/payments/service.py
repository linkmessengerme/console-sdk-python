"""Mini Apps merchant API, with separate payments-scoped OAuth transport."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, TypeVar

from .._internal.transport import AsyncHttpTransport, HttpTransport
from ..errors import InvalidResponseError, ValidationError
from .types import (
    CancelOrderRequest,
    CancelOrderResponse,
    CancelOrderResultCode,
    Checkout,
    CreateOrderRequest,
    CreateOrderResponse,
    CreateOrderResultCode,
    Environment,
    FulfillmentStatus,
    GetOrderByMerchantReferenceRequest,
    GetOrderByMerchantReferenceResponse,
    GetOrderRequest,
    GetOrderResponse,
    Offer,
    Order,
    OrderStatus,
    ProductKind,
    ProductSnapshot,
    RecordFulfillmentRequest,
    RecordFulfillmentResponse,
    RecordFulfillmentResultCode,
    TestOutcome,
)

_ORDERS = "/sdk/v1/miniapps/payments/orders"
_T = TypeVar("_T")
_Request = (
    CreateOrderRequest
    | GetOrderRequest
    | GetOrderByMerchantReferenceRequest
    | CancelOrderRequest
    | RecordFulfillmentRequest
)


def _positive_int64(value: int) -> str:
    if type(value) is not int or not 0 < value <= 9223372036854775807:
        raise ValidationError("payment amount/version must be a positive int64 integer")
    return str(value)


def _body(req: _Request) -> dict[str, Any]:
    body = asdict(req)
    if "operation_id" in body:
        op = body["operation_id"]
        if (
            not isinstance(op, str)
            or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", op)
            or op == "00000000-0000-0000-0000-000000000000"
        ):
            raise ValidationError("operation_id must be a persisted nonzero UUID; retry unchanged")
    if isinstance(req, CreateOrderRequest):
        body["product"]["version"] = _positive_int64(req.product.version)
        body["payment"]["amount_minor"] = _positive_int64(req.payment.amount_minor)
        if req.test_outcome == TestOutcome.UNSPECIFIED:
            del body["test_outcome"]
    if isinstance(req, RecordFulfillmentRequest):
        body["product_version"] = _positive_int64(req.product_version)
    return body


def _string(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("expected string")
    return value


def _int64(value: Any) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"-?(0|[1-9][0-9]{0,18})", value):
        raise ValueError("expected int64 decimal string")
    result = int(value)
    if not -9223372036854775808 <= result <= 9223372036854775807:
        raise ValueError("int64 out of range")
    return result


def _timestamp(value: Any) -> str | None:
    # Preserve ProtoJSON nanoseconds rather than rounding to datetime microseconds.
    return None if value is None else _string(value)


def _order(o: dict[str, Any]) -> Order:
    p, offer = o["product"], o["offer"]
    return Order(
        order_id=_string(o["order_id"]),
        app_id=_string(o["app_id"]),
        environment=Environment(o["environment"]),
        merchant_order_id=_string(o["merchant_order_id"]),
        buyer_sub=_string(o["buyer_sub"]),
        product=ProductSnapshot(
            sku=_string(p["sku"]),
            version=_int64(p["version"]),
            name=_string(p["name"]),
            kind=ProductKind(p["kind"]),
        ),
        offer=Offer(
            offer_id=_string(offer["offer_id"]),
            version=_int64(offer["version"]),
            amount_minor=_int64(offer["amount_minor"]),
            currency=_string(offer["currency"]),
            method=_string(offer["method"]),
        ),
        status=OrderStatus(o["status"]),
        fulfillment_status=FulfillmentStatus(o["fulfillment_status"]),
        revision=_int64(o.get("revision", "0")),
        created_at=_timestamp(o.get("created_at")),
        expires_at=_timestamp(o.get("expires_at")),
        paid_at=_timestamp(o.get("paid_at")),
    )


def _create(wire: dict[str, Any]) -> CreateOrderResponse:
    result = CreateOrderResultCode(wire["result"])
    if result == CreateOrderResultCode.UNSPECIFIED:
        raise ValueError("unspecified result")
    c = wire.get("checkout")
    checkout = None
    if c is not None:
        available = c.get("method_available", False)
        if not isinstance(available, bool):
            raise ValueError("expected bool")
        checkout = Checkout(
            order=_order(c["order"]),
            checkout_session_id=_string(c["checkout_session_id"]),
            method_available=available,
        )
    if result == CreateOrderResultCode.OK and checkout is None:
        raise ValueError("missing checkout")
    return CreateOrderResponse(result=result, checkout=checkout)


def _get(wire: dict[str, Any]) -> GetOrderResponse:
    return GetOrderResponse(order=_order(wire["order"]))


def _by_reference(wire: dict[str, Any]) -> GetOrderByMerchantReferenceResponse:
    return GetOrderByMerchantReferenceResponse(order=_order(wire["order"]))


def _cancel(wire: dict[str, Any]) -> CancelOrderResponse:
    result = CancelOrderResultCode(wire["result"])
    if result == CancelOrderResultCode.UNSPECIFIED:
        raise ValueError("unspecified result")
    order = _order(wire["order"]) if wire.get("order") is not None else None
    if result != CancelOrderResultCode.IDEMPOTENCY_CONFLICT and order is None:
        raise ValueError("missing order")
    return CancelOrderResponse(result=result, order=order)


def _fulfillment(wire: dict[str, Any]) -> RecordFulfillmentResponse:
    result = RecordFulfillmentResultCode(wire["result"])
    if result == RecordFulfillmentResultCode.UNSPECIFIED:
        raise ValueError("unspecified result")
    order = _order(wire["order"]) if wire.get("order") is not None else None
    if result != RecordFulfillmentResultCode.IDEMPOTENCY_CONFLICT and order is None:
        raise ValueError("missing order")
    return RecordFulfillmentResponse(result=result, order=order)


def _decode(wire: dict[str, Any], decoder: Callable[[dict[str, Any]], _T]) -> _T:
    try:
        return decoder(wire)
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise InvalidResponseError("invalid payments response") from err


class PaymentsService:
    """Mini Apps merchant API. Native checkout and item grants belong to their hosts."""

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def create_order(self, request: CreateOrderRequest) -> CreateOrderResponse:
        """Persist the request before sending; inspect result even on HTTP 200."""
        wire = self._transport.do_json("POST", _ORDERS + "", _body(request), retry_safe=True)
        return _decode(wire, _create)

    def get_order(self, request: GetOrderRequest) -> GetOrderResponse:
        """Read authoritative order state before granting an item."""
        wire = self._transport.do_json("POST", _ORDERS + "/get", _body(request), retry_safe=True)
        return _decode(wire, _get)

    def get_order_by_merchant_reference(
        self, request: GetOrderByMerchantReferenceRequest
    ) -> GetOrderByMerchantReferenceResponse:
        """Find an order by its merchant reference, within the app and environment."""
        wire = self._transport.do_json(
            "POST", _ORDERS + "/by-merchant-reference", _body(request), retry_safe=True
        )
        return _decode(wire, _by_reference)

    def cancel_order(self, request: CancelOrderRequest) -> CancelOrderResponse:
        """Cancel an order; this is not a refund. Inspect the business result."""
        wire = self._transport.do_json("POST", _ORDERS + "/cancel", _body(request), retry_safe=True)
        return _decode(wire, _cancel)

    def record_fulfillment(self, request: RecordFulfillmentRequest) -> RecordFulfillmentResponse:
        """Record an item grant and receipt already committed after observing PAID."""
        wire = self._transport.do_json(
            "POST", _ORDERS + "/fulfillment", _body(request), retry_safe=True
        )
        return _decode(wire, _fulfillment)


class AsyncPaymentsService:
    """Mini Apps merchant API. Native checkout and item grants belong to their hosts."""

    def __init__(self, transport: AsyncHttpTransport) -> None:
        self._transport = transport

    async def create_order(self, request: CreateOrderRequest) -> CreateOrderResponse:
        """Persist the request before sending; inspect result even on HTTP 200."""
        wire = await self._transport.do_json("POST", _ORDERS + "", _body(request), retry_safe=True)
        return _decode(wire, _create)

    async def get_order(self, request: GetOrderRequest) -> GetOrderResponse:
        """Read authoritative order state before granting an item."""
        wire = await self._transport.do_json(
            "POST", _ORDERS + "/get", _body(request), retry_safe=True
        )
        return _decode(wire, _get)

    async def get_order_by_merchant_reference(
        self, request: GetOrderByMerchantReferenceRequest
    ) -> GetOrderByMerchantReferenceResponse:
        """Find an order by its merchant reference, within the app and environment."""
        wire = await self._transport.do_json(
            "POST", _ORDERS + "/by-merchant-reference", _body(request), retry_safe=True
        )
        return _decode(wire, _by_reference)

    async def cancel_order(self, request: CancelOrderRequest) -> CancelOrderResponse:
        """Cancel an order; this is not a refund. Inspect the business result."""
        wire = await self._transport.do_json(
            "POST", _ORDERS + "/cancel", _body(request), retry_safe=True
        )
        return _decode(wire, _cancel)

    async def record_fulfillment(
        self, request: RecordFulfillmentRequest
    ) -> RecordFulfillmentResponse:
        """Record an item grant and receipt already committed after observing PAID."""
        wire = await self._transport.do_json(
            "POST", _ORDERS + "/fulfillment", _body(request), retry_safe=True
        )
        return _decode(wire, _fulfillment)
