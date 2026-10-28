"""Test-only merchant lifecycle; does not run native checkout or grant goods."""
import json
import os
from pathlib import Path

from link_console_sdk import ConsoleClient, payments


def main() -> None:
    key = json.loads(Path(os.environ["LINK_TEST_KEY_FILE"]).read_text())
    if key.get("environment") != "test":
        raise ValueError("this example requires Test credentials")
    # Persist these UUIDs and the entire request in your backend before sending.
    # Reuse them unchanged when rerunning after a lost response.
    request = payments.CreateOrderRequest(
        app_id=os.environ["LINK_APP_ID"],
        operation_id=os.environ["LINK_CREATE_OPERATION_ID"],
        merchant_order_id=os.environ["LINK_MERCHANT_ORDER_ID"],
        # From your authenticated Mini App backend session, not an arbitrary JS identity.
        buyer_sub=os.environ["LINK_VERIFIED_BUYER_SUB"],
        product=payments.ProductSnapshot(
            sku="coins-100", version=1, name="100 coins", kind=payments.ProductKind.CONSUMABLE,
        ),
        payment=payments.PaymentTerms(
            amount_minor=1250,
            currency=os.environ["LINK_PAYMENT_CURRENCY"],
            method=os.environ["LINK_PAYMENT_METHOD"],
        ),
        test_outcome=payments.TestOutcome.SUCCESS,
    )
    cancel_operation_id = os.environ["LINK_CANCEL_OPERATION_ID"]
    if cancel_operation_id == request.operation_id:
        raise ValueError("use distinct persisted UUIDs for create and cancel")
    with ConsoleClient.from_credentials_json(key) as client:
        created = client.payments.create_order(request)
        if created.result != payments.CreateOrderResultCode.OK:
            raise RuntimeError(f"business result: {created.result.value}")
        assert created.checkout is not None
        order_id = created.checkout.order.order_id
        current = client.payments.get_order(payments.GetOrderRequest(request.app_id, order_id))
        found = client.payments.get_order_by_merchant_reference(
            payments.GetOrderByMerchantReferenceRequest(request.app_id, request.merchant_order_id)
        )
        if found.order.order_id != order_id:
            raise RuntimeError("merchant reference mismatch")
        cancelled = client.payments.cancel_order(payments.CancelOrderRequest(
            app_id=request.app_id, order_id=order_id, operation_id=cancel_operation_id,
        ))
        print(order_id, current.order.status.value, cancelled.result.value)
    # RecordFulfillment is demonstrated in README.md: only after PAID and an
    # idempotent item grant + durable receipt committed in your own database.


if __name__ == "__main__":
    main()
