# link-console-sdk

Official **Python** SDK for the **Link Developer Platform** (Console API).
Send OTP codes, read authorized Login/Mini Apps user data and manage Mini App
merchant payments with **sync** and **async** clients.

- Sync (`ConsoleClient`) **and** async (`AsyncConsoleClient`), both on `httpx`.
- OTP OAuth2 `client_credentials` via `private_key_jwt` (Ed25519) — app tokens are
  minted, cached and re-minted transparently.
- Automatic idempotency keys and retries for OTP; per-call user tokens for UserInfo.
- Mini Apps merchant payments with a separate `payments` OAuth scope.
- Fully typed (`py.typed`), typed errors you can branch on.

> Requires **Python ≥ 3.10**. Runtime deps: `httpx`, `cryptography`, `PyJWT`.

## Install

```bash
pip install link-console-sdk
```

## Quickstart

Download an OAuth-client key file from the Developer Console and load it — the
SDK reads both your credentials **and the API endpoint** (`api_base_url`) from
the key:

```python
from link_console_sdk import ConsoleClient

with ConsoleClient.from_key_file("link-oauth-client.json") as client:
    res = client.otp.send(phone="+12025550123", code="123456")
    print(res.request_id, res.status)
```

### Async

```python
import asyncio
from link_console_sdk import AsyncConsoleClient


async def main() -> None:
    async with AsyncConsoleClient.from_key_file("link-oauth-client.json") as client:
        res = await client.otp.send(phone="+12025550123", code="123456")
        print(res.request_id, res.status)


asyncio.run(main())
```

## OTP authentication

OTP authenticates with OAuth2 `client_credentials` using a `private_key_jwt`
client assertion (Ed25519). On the first OTP call (and whenever the cached token is
near expiry, or after a `401`), it signs a short-lived assertion with your
private key, exchanges it at `token_url` for an app access token, and caches that
token until it expires. This is the Firebase Admin SDK model: the private key
stays on your backend, so a fresh token can be minted any time and no
`refresh_token` is needed.

### Credentials file

When you create (or rotate) an OAuth client in Console you download a JSON
key-file:

```json
{
  "type": "link_oauth_client",
  "client_id": "lk_client_xxxxxxxx",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
  "token_url": "https://api.example.com/oauth/v1/token",
  "api_base_url": "https://api.example.com",
  "issuer": "https://api.example.com",
  "environment": "live",
  "project_id": "my-project-a1b2c3"
}
```

- `private_key` is a PKCS#8 Ed25519 key in PEM form. It is issued once at key
  creation; Console keeps only the public key. Treat it like a password — the
  SDK never logs or prints it.
- `token_url` and `issuer` are optional — when omitted they are derived from
  `api_base_url` (`.../oauth/v1/token` and `api_base_url` respectively).

### Without a key file

Provide the client id + PEM key + base URL directly (there is **no built-in
default endpoint**, so requests always go where your key points):

```python
import os
from link_console_sdk import ConsoleClient

client = ConsoleClient(
    client_id=os.environ["LINK_CLIENT_ID"],
    private_key=os.environ["LINK_PRIVATE_KEY"],  # PEM Ed25519 ("private_key")
    base_url=os.environ["LINK_API_BASE_URL"],    # your key's api_base_url
)
```

`ConsoleClient.from_credentials_json(...)` accepts the same key-file contents as
a JSON string, `bytes`, or an already-parsed `dict`.

## Sending OTP

```python
res = client.otp.send(
    phone="+12025550123",
    code="482913",
    locale="ru",                 # optional; auto-detected from the phone otherwise
    template_id="tpl_abc123",    # optional; project default used otherwise
    variables={"name": "Alex"},  # optional template vars ({{code}} is automatic)
    idempotency_key="order-42",  # optional; auto-generated (UUID v4) otherwise
)
```

`Locale` constants are exported for convenience:

```python
from link_console_sdk import Locale

client.otp.send(phone="+12025550123", code="123456", locale=Locale.RUSSIAN)
```

`Locale.RUSSIAN`, `Locale.ENGLISH`, `Locale.KAZAKH`, `Locale.UZBEK` — or any
ISO 639-1 string the platform supports. Omit `locale` to auto-detect from the
phone.

The response reports `template_used` (a template id or `"fallback"`) and
`locale_used` (the locale actually used after resolution).

## Login and Mini Apps UserInfo

For Login with your own backend, use standalone `LoginClient` or
`AsyncLoginClient` below; they require no OTP key file.

Use the same client with a **user access token** supplied per call:

```python
with ConsoleClient.from_key_file("link-oauth-client.json") as client:
    # Login: access token from the user's completed Login authorization flow.
    user = client.login.get_user_info(login_access_token, expected_sub=verified_session_sub)
    if user.phone_number is not None:
        pass  # Use the number for the authorized operation; do not log it.

    # Mini Apps: accessToken from LinkMiniApp.init() (the ma_ token).
    mini_user = client.mini_apps.get_user_info(
        mini_app_access_token, expected_sub=verified_mini_app_session_sub,
    )

# Both methods also exist on AsyncConsoleClient:
async with AsyncConsoleClient.from_key_file("link-oauth-client.json") as client:
    user = await client.login.get_user_info(login_access_token)
    mini_user = await client.mini_apps.get_user_info(mini_app_access_token)
```

Only the access token is required. Do not pass a user ID, a scope list, an ID
token, or an app `client_credentials` token. Request `phone` during Login
authorization or enable it in Mini Apps Permissions; the project must have the
scope approved and the user must consent. The API returns currently authorized
fields. `phone_number` is `None` when unavailable. `phone_number_verified` is a
separate optional bool, currently omitted by Link; absence does not mean `False`
or proof of ownership. Login also returns `name`, `preferred_username`, `picture`;
Mini Apps returns optional `profile` (`name`, `username`, `avatar_url`).

If the frontend obtained the token, send it through your own authenticated HTTPS
API. `expected_sub` optionally compares against `sub` from your already verified
Login/Mini App session. These methods do not verify an ID token or establish a
backend session themselves.

UserInfo calls `GET /oauth/v1/userinfo` or `GET /miniapps/v1/userinfo` at the
configured `base_url`. Use a trusted HTTPS API origin with no path prefix, query,
credentials or fragment (HTTP on loopback is allowed for development). Requests
use only the supplied user bearer, omit cookies/default client auth/query
parameters, and never follow redirects, exchange app tokens, retry, or cache user
data. Responses are limited to 64 KiB. `InvalidResponseError` covers malformed
data or subject mismatch; errors omit raw response data and transport causes.

Handle `AuthenticationError` by obtaining a fresh token through the original
authorization/session flow. Mini App tokens last 60 seconds; the host reissues
an expired one as a new launch, and the frontend can obtain the current token from `init()` and pass it to
the backend. The server SDK does not refresh either kind of user token.

## Verify a Login ID token on your backend

```python
from link_console_sdk import LoginClient

# Reuse a client for your process/server lifetime; public Console configuration only.
with LoginClient(
    issuer="https://api-sdk.linkmessenger.me",
    api_base_url="https://api-sdk-fr.linkmessenger.me",  # optional regional origin
    client_ids=["YOUR_IOS_LOGIN_CLIENT_ID", "YOUR_ANDROID_LOGIN_CLIENT_ID"],
) as login:
    # saved_challenge was created on YOUR backend before sign-in, then consumed once.
    identity = login.verify_id_token(id_token, nonce=saved_challenge.nonce)
    profile = login.get_user_info(login_access_token, expected_sub=identity.sub)
    # Map (identity.issuer, identity.sub) to your account. Check profile.phone_number
    # if your application requires a phone, then issue your own session tokens.
```

The async API uses `async with AsyncLoginClient(...)`,
`await login.verify_id_token(id_token, nonce=...)` and
`await login.get_user_info(access_token, expected_sub=...)` with the same options.
Reuse the async client within one event loop. An optional `http_client` accepts
an `httpx.Client` / `httpx.AsyncClient`; an injected client remains caller-owned.

Verification checks EdDSA signature, `kid`, exact configured issuer, one allowed
audience, matching `azp`, subject, `iat`/`exp`/optional `nbf` (30-second clock
tolerance), and required expected nonce. It returns frozen `IDTokenClaims`:
`issuer`, `sub`, `client_id`, `nonce`, `issued_at`, `expires_at` (Unix seconds).
Access tokens and refreshed ID tokens without nonce are rejected. This verifier
is for Link Login, not Mini App tokens.

`IDTokenError` means rejected identity; `LoginKeySourceError` means discovery/keys
are unavailable; `ConfigError` means invalid configuration. Discovery and JWKS
use only the configured API origin, with no credentials, cookies or redirects.
Keys are cached for five minutes, concurrent loads are coalesced, unknown-key
refreshes are limited to once per 30 seconds, failures can retry after one
second. HTTP operations have five-second timeouts; async key loading has a
five-second overall deadline. No app private key is required.

Create nonce on the backend using `secrets.token_urlsafe(32)`, save it in a
short-lived one-use challenge, and pass it to native sign-in. Allowed format:
32–256 base64url characters. Never use the incoming JWT's nonce as the expected
value. The SDK compares nonce; your backend atomically consumes the challenge.
Signature verification does not query revocation or issue your app session.
Read fresh authorized profile/phone through UserInfo with the verified subject.

The complete [own-backend example](https://github.com/linkmessengerme/console-sdk-node/tree/main/examples/own-backend)
shows the same flow in Node, including Swift/Kotlin integration, one-use challenge,
own access/refresh tokens, rotation, refresh reuse revocation and logout.

## Mini Apps merchant payments

Both `ConsoleClient` and `AsyncConsoleClient` expose `client.payments`. Import typed
request/response dataclasses and enums from `link_console_sdk.payments`:

```python
from link_console_sdk import ConsoleClient, payments

with ConsoleClient.from_key_file("link-test-key.json") as client:
    # IDs and buyer_sub come from persisted, authenticated backend state.
    created = client.payments.create_order(payments.CreateOrderRequest(
        app_id=app_id, operation_id=saved_create_operation_id,
        merchant_order_id=merchant_order_id, buyer_sub=verified_buyer_sub,
        product=payments.ProductSnapshot(
            sku="coins-100", version=1, name="100 coins", kind=payments.ProductKind.CONSUMABLE,
        ),
        # currency and method: the values your Mini App is enabled for in Link Console.
        payment=payments.PaymentTerms(amount_minor=1250, currency=currency, method=method),
        test_outcome=payments.TestOutcome.SUCCESS,
    ))
    if created.result != payments.CreateOrderResultCode.OK:
        raise RuntimeError(f"create result: {created.result.value}")
    assert created.checkout is not None
    order_id = created.checkout.order.order_id
    current = client.payments.get_order(payments.GetOrderRequest(app_id, order_id))
    found = client.payments.get_order_by_merchant_reference(
        payments.GetOrderByMerchantReferenceRequest(app_id, merchant_order_id)
    )
    # A separate operation, if you want to cancel:
    cancelled = client.payments.cancel_order(payments.CancelOrderRequest(
        app_id=app_id, order_id=order_id, operation_id=saved_cancel_operation_id,
    ))
```

The async API accepts the same dataclasses: `await client.payments.create_order(request)`,
`get_order`, `get_order_by_merchant_reference`, `cancel_order`, `record_fulfillment`.
Int64 amounts, product/offer versions and revisions are Python `int`, checked against
the signed 64-bit range and encoded as decimal strings on the wire. Amounts are
positive minor currency units; floats and booleans are rejected. Timestamps remain
ProtoJSON RFC 3339 strings to preserve nanoseconds; absent `paid_at` is `None`.

```python
# Separate from cancellation: only after PAID and your durable grant/receipt commit.
ack = client.payments.record_fulfillment(payments.RecordFulfillmentRequest(
    app_id=app_id, order_id=paid_order.order_id, operation_id=saved_fulfillment_operation_id,
    receipt_id=committed_receipt_id, sku=paid_order.product.sku,
    product_version=paid_order.product.version, buyer_sub=paid_order.buyer_sub,
))
if ack.result != payments.RecordFulfillmentResultCode.OK:
    raise RuntimeError(f"fulfillment result: {ack.result.value}")
```

The same server OAuth key can serve OTP and payments. Payment methods lazily
request **only `scope=payments`**; OTP continues requesting `scope=otp`. Each scope
has a separate token cache and refresh, so enabling this API does not require
payments permission for OTP-only clients. The OAuth client must allow the requested
scope. Mini App payment access is a separate per-app **Test/Live grant** in the
payments database; a scope alone does not grant access. Both environments require
their own active grant. Environment, project and workspace come from the server
token and cannot be supplied in a payment request.

The backend obtains `buyer_sub` from its authenticated, verified Mini App session
and computes the product snapshot and price itself. Do not trust a buyer identity
or price supplied by Mini App JavaScript. The merchant API does not accept internal
user IDs, phone numbers or OTP codes. Native checkout (`StartAttempt`, OTP,
`ConfirmAttempt`) belongs to the Link host through the native checkout API and requires
the user's Link session. Merchant OAuth cannot replace that session.

All five methods send POST with `Content-Type` and `Accept: application/json`,
using the gateway's ProtoJSON contract (snake_case fields and full enum names):

| Operation | Path suffix after `/sdk/v1/miniapps/payments/orders` |
| --- | --- |
| CreateOrder | empty suffix |
| GetOrder | `/get` |
| GetOrderByMerchantReference | `/by-merchant-reference` |
| CancelOrder | `/cancel` |
| RecordFulfillment | `/fulfillment` |

Persist the complete mutation request **before** sending it, including a nonzero
UUID `operation_id`. Use a distinct UUID for each create, cancel or fulfillment
operation; reuse the same UUID and identical body after timeouts, lost responses
or process restarts. The SDK does not generate this business key. Payments use
body-level idempotency, not the OTP `Idempotency-Key` header. Reads and mutations
with a validated operation UUID use the configured transient retry policy; 401
refreshes only the payment token. Business refusals are never retried automatically.

HTTP 200 means the request was processed, not that the purchase succeeded. Inspect
`result`: create can return access-not-approved/revoked, method-not-available or
idempotency-conflict; cancel can return order-expired, already-paid,
attempt-in-progress, cancelled or idempotency-conflict; fulfillment can return
fulfillment-conflict or idempotency-conflict. The exported result enums preserve
the exact `*_RESULT_CODE_*` wire values. `checkout` can be absent on a create
refusal; `order` can be absent on a cancel/fulfillment idempotency conflict.

Non-2xx ProtoJSON `ApiError` responses use the existing SDK error classes, preserving
`ERROR_CODE_*`, request ID and details (`trace_id`, `field_violations`, `rate_limit`).
401/403 map to authentication errors; 429 maps to rate-limit errors. A missing order
is HTTP 404. OTP's existing error envelope remains supported.

Order states are only `OPEN`, `PROCESSING`, `PAID`, `CANCELLED`, `EXPIRED` (plus the
proto `UNSPECIFIED` value). Fulfillment states are `NOT_REQUESTED`, `PENDING`,
`FULFILLED` (plus `UNSPECIFIED`). Poll the merchant order for authoritative state;
a successful create or native UI callback is not proof of payment. Cancellation is
not a refund. After observing `PAID`, commit your item grant and durable receipt
idempotently in your own database, then record that receipt with `RecordFulfillment`.
That method records an existing grant; it does not grant the item. On a conflict,
reconcile the receipt and returned order rather than granting again.

The [Test merchant example](examples/payments_test.py) creates, reads, looks up and cancels an
order. It refuses a key file whose environment is not `test`. Set `LINK_TEST_KEY_FILE`,
`LINK_APP_ID`, `LINK_VERIFIED_BUYER_SUB`, `LINK_MERCHANT_ORDER_ID`, `LINK_PAYMENT_CURRENCY`,
`LINK_PAYMENT_METHOD`, and distinct persisted
`LINK_CREATE_OPERATION_ID` / `LINK_CANCEL_OPERATION_ID` UUIDs, then run `python examples/payments_test.py`.
The app needs a Test grant. `test_outcome` can be SUCCESS, INSUFFICIENT or DELAYED in
Test only; omit it (or use UNSPECIFIED) for Live. Creating a Test order alone does
not execute the native payment flow. The example does not confirm payments or grant
items. Fulfillment requires a separately completed PAID purchase and durable receipt.

## Idempotency & retries

Every OTP request carries an idempotency key (auto-generated unless you pass one).
Because the request is idempotent, the SDK safely **retries** transient failures
— network errors, timeouts, `408/429/5xx`, and the "request in progress"
conflict — with exponential backoff + jitter. Pass your own `idempotency_key` to
deduplicate across process restarts.

```python
from link_console_sdk import ConsoleClient, RetryConfig

ConsoleClient(..., retry=RetryConfig(max_retries=4))  # tune
ConsoleClient(..., retry=False)                        # disable
```

## Error handling

Every error extends `LinkError`. Branch with `isinstance`:

```python
from link_console_sdk import (
    AuthenticationError,
    APIError,
    RateLimitError,
    ValidationError,
)

try:
    client.otp.send(phone=phone, code=code)
except RateLimitError as err:
    print("retry after", err.retry_after)
except AuthenticationError:
    print("bad credentials / token")
except APIError as err:
    print(err.code, err.status_code, err.request_id)
except ValidationError as err:
    print("bad input:", err)
```

| Error | When |
|---|---|
| `ValidationError` | Bad phone, code or idempotency key (raised before any request) |
| `ConfigError` | Invalid credentials or client options |
| `AuthenticationError` | `INVALID_TOKEN` / `INSUFFICIENT_SCOPE`, or a rejected client assertion |
| `InvalidResponseError` | Invalid UserInfo data or subject mismatch |
| `IdempotencyError` | `IDEMPOTENCY_KEY_CONFLICT` (same key, different payload) |
| `RateLimitError` | `TOO_MANY_REQUESTS` (`retry_after` may be absent) |
| `APIError` | Any other non-2xx (`status_code`, `code`, `details`, `request_id`) |
| `ConnectionError` | Network failure, timeout, or abort |

> `ConnectionError` is the SDK's own type (it shadows the built-in inside this
> package's namespace). Import it from `link_console_sdk`.

## Configuration

| Option | Default | Description |
|---|---|---|
| `client_id`, `private_key`, `base_url` | — | Credentials + endpoint (required for the direct constructor; read from the key by `from_key_file` / `from_credentials_json`) |
| `token_url`, `issuer` | derived from `base_url` | Override the token endpoint / assertion audience |
| `timeout` | `10.0` | Per-request timeout, in seconds |
| `retry` | `RetryConfig(max_retries=2, initial_backoff=0.1, max_backoff=2.0)` | OTP retry policy, or `False` |
| `user_agent_suffix` | — | Appended to the `User-Agent` |
| `http_client` | managed | Inject your own `httpx.Client` / `httpx.AsyncClient` (proxy, instrumentation, tests) |

## Development

```bash
pip install -e ".[dev]"
pytest          # tests
mypy            # type-check
ruff check .    # lint
```

## License

MIT
