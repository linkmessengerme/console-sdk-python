# link-console-sdk

Official **Python** SDK for the **Link Developer Platform** (Console API).
Send OTP codes to your users through the Link bot in a couple of lines — with a
**sync** and an **async** client that share the same API.

- Sync (`ConsoleClient`) **and** async (`AsyncConsoleClient`), both on `httpx`.
- OAuth2 `client_credentials` via `private_key_jwt` (Ed25519) — tokens are
  minted, cached and re-minted transparently.
- Automatic idempotency keys, transparent retries with backoff + jitter.
- Fully typed (`py.typed`), typed errors you can branch on.

> Requires **Python ≥ 3.10**. Runtime deps: `httpx`, `cryptography`.

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

## Authentication

The SDK authenticates with OAuth2 `client_credentials` using a `private_key_jwt`
client assertion (Ed25519). On the first call (and whenever the cached token is
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

## Idempotency & retries

Every request carries an idempotency key (auto-generated unless you pass one).
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
| `IdempotencyError` | `IDEMPOTENCY_KEY_CONFLICT` (same key, different payload) |
| `RateLimitError` | `TOO_MANY_REQUESTS` (carries `retry_after`) |
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
| `retry` | `RetryConfig(max_retries=2, initial_backoff=0.1, max_backoff=2.0)` | Retry policy, or `False` |
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
