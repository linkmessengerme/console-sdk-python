"""Mini Apps merchant types. Amounts are minor currency units; int64 uses Python int."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CreateOrderResultCode(str, Enum):
    UNSPECIFIED = "CREATE_ORDER_RESULT_CODE_UNSPECIFIED"
    OK = "CREATE_ORDER_RESULT_CODE_OK"
    PAYMENT_ACCESS_NOT_APPROVED = "CREATE_ORDER_RESULT_CODE_PAYMENT_ACCESS_NOT_APPROVED"
    PAYMENT_ACCESS_REVOKED = "CREATE_ORDER_RESULT_CODE_PAYMENT_ACCESS_REVOKED"
    METHOD_NOT_AVAILABLE = "CREATE_ORDER_RESULT_CODE_METHOD_NOT_AVAILABLE"
    IDEMPOTENCY_CONFLICT = "CREATE_ORDER_RESULT_CODE_IDEMPOTENCY_CONFLICT"


class CancelOrderResultCode(str, Enum):
    UNSPECIFIED = "CANCEL_ORDER_RESULT_CODE_UNSPECIFIED"
    OK = "CANCEL_ORDER_RESULT_CODE_OK"
    ORDER_EXPIRED = "CANCEL_ORDER_RESULT_CODE_ORDER_EXPIRED"
    ALREADY_PAID = "CANCEL_ORDER_RESULT_CODE_ALREADY_PAID"
    IDEMPOTENCY_CONFLICT = "CANCEL_ORDER_RESULT_CODE_IDEMPOTENCY_CONFLICT"
    ATTEMPT_IN_PROGRESS = "CANCEL_ORDER_RESULT_CODE_ATTEMPT_IN_PROGRESS"
    CANCELLED = "CANCEL_ORDER_RESULT_CODE_CANCELLED"


class RecordFulfillmentResultCode(str, Enum):
    UNSPECIFIED = "RECORD_FULFILLMENT_RESULT_CODE_UNSPECIFIED"
    OK = "RECORD_FULFILLMENT_RESULT_CODE_OK"
    IDEMPOTENCY_CONFLICT = "RECORD_FULFILLMENT_RESULT_CODE_IDEMPOTENCY_CONFLICT"
    FULFILLMENT_CONFLICT = "RECORD_FULFILLMENT_RESULT_CODE_FULFILLMENT_CONFLICT"


class Environment(str, Enum):
    UNSPECIFIED = "ENVIRONMENT_UNSPECIFIED"
    TEST = "ENVIRONMENT_TEST"
    LIVE = "ENVIRONMENT_LIVE"


class ProductKind(str, Enum):
    UNSPECIFIED = "PRODUCT_KIND_UNSPECIFIED"
    CONSUMABLE = "PRODUCT_KIND_CONSUMABLE"
    NON_CONSUMABLE = "PRODUCT_KIND_NON_CONSUMABLE"


class TestOutcome(str, Enum):
    UNSPECIFIED = "TEST_OUTCOME_UNSPECIFIED"
    SUCCESS = "TEST_OUTCOME_SUCCESS"
    INSUFFICIENT = "TEST_OUTCOME_INSUFFICIENT"
    DELAYED = "TEST_OUTCOME_DELAYED"


class OrderStatus(str, Enum):
    UNSPECIFIED = "ORDER_STATUS_UNSPECIFIED"
    OPEN = "ORDER_STATUS_OPEN"
    PROCESSING = "ORDER_STATUS_PROCESSING"
    PAID = "ORDER_STATUS_PAID"
    CANCELLED = "ORDER_STATUS_CANCELLED"
    EXPIRED = "ORDER_STATUS_EXPIRED"


class FulfillmentStatus(str, Enum):
    UNSPECIFIED = "FULFILLMENT_STATUS_UNSPECIFIED"
    NOT_REQUESTED = "FULFILLMENT_STATUS_NOT_REQUESTED"
    PENDING = "FULFILLMENT_STATUS_PENDING"
    FULFILLED = "FULFILLMENT_STATUS_FULFILLED"


@dataclass(frozen=True, slots=True)
class CreateOrderRequest:
    app_id: str
    operation_id: str
    merchant_order_id: str
    buyer_sub: str
    product: ProductSnapshot
    payment: PaymentTerms
    test_outcome: TestOutcome = TestOutcome.UNSPECIFIED


@dataclass(frozen=True, slots=True)
class CreateOrderResponse:
    result: CreateOrderResultCode
    checkout: Checkout | None = None


@dataclass(frozen=True, slots=True)
class GetOrderRequest:
    app_id: str
    order_id: str


@dataclass(frozen=True, slots=True)
class GetOrderResponse:
    order: Order


@dataclass(frozen=True, slots=True)
class GetOrderByMerchantReferenceRequest:
    app_id: str
    merchant_order_id: str


@dataclass(frozen=True, slots=True)
class GetOrderByMerchantReferenceResponse:
    order: Order


@dataclass(frozen=True, slots=True)
class CancelOrderRequest:
    app_id: str
    order_id: str
    operation_id: str


@dataclass(frozen=True, slots=True)
class CancelOrderResponse:
    result: CancelOrderResultCode
    order: Order | None = None


@dataclass(frozen=True, slots=True)
class RecordFulfillmentRequest:
    app_id: str
    order_id: str
    operation_id: str
    receipt_id: str
    sku: str
    product_version: int
    buyer_sub: str


@dataclass(frozen=True, slots=True)
class RecordFulfillmentResponse:
    result: RecordFulfillmentResultCode
    order: Order | None = None


@dataclass(frozen=True, slots=True)
class ProductSnapshot:
    sku: str
    version: int
    name: str
    kind: ProductKind


@dataclass(frozen=True, slots=True)
class PaymentTerms:
    amount_minor: int
    currency: str
    method: str


@dataclass(frozen=True, slots=True)
class Offer:
    offer_id: str
    version: int
    amount_minor: int
    currency: str
    method: str


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    app_id: str
    environment: Environment
    merchant_order_id: str
    buyer_sub: str
    product: ProductSnapshot
    offer: Offer
    status: OrderStatus
    fulfillment_status: FulfillmentStatus
    revision: int
    created_at: str | None = None
    expires_at: str | None = None
    paid_at: str | None = None


@dataclass(frozen=True, slots=True)
class Checkout:
    order: Order
    checkout_session_id: str
    method_available: bool
