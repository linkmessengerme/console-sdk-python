"""Official Python SDK for the Link Developer Platform (Console API).

Send OTP codes to your users through the Link bot:

.. code-block:: python

    from link_console_sdk import ConsoleClient

    client = ConsoleClient.from_key_file("link-oauth-client.json")
    res = client.otp.send(phone="+12025550123", code="123456")
    print(res.request_id, res.status)

An async client (:class:`AsyncConsoleClient`) exposes the same API with
``await``.
"""

from __future__ import annotations

from . import payments
from ._internal.idempotency import new_idempotency_key
from ._version import VERSION
from .client import AsyncConsoleClient, ConsoleClient
from .credentials import Credentials
from .errors import (
    APIError,
    AuthenticationError,
    ConfigError,
    ConnectionError,
    IdempotencyError,
    InvalidResponseError,
    LinkError,
    RateLimitError,
    ValidationError,
    is_api_error,
    is_authentication_error,
    is_connection_error,
    is_idempotency_error,
    is_link_error,
    is_rate_limit_error,
    is_validation_error,
)
from .login import AsyncLoginClient, IDTokenClaims, IDTokenError, LoginClient, LoginKeySourceError
from .options import DEFAULT_RETRY, DEFAULT_TIMEOUT, RetryConfig
from .otp import AsyncOtpService, Locale, OtpService, SendResponse
from .payments import AsyncPaymentsService, PaymentsService
from .userinfo import (
    AsyncLoginService,
    AsyncMiniAppsService,
    LoginService,
    LoginUserInfo,
    MiniAppProfile,
    MiniAppsService,
    MiniAppUserInfo,
    UserInfo,
)

__version__ = VERSION

__all__ = [
    "VERSION",
    "__version__",
    # Clients
    "ConsoleClient",
    "AsyncConsoleClient",
    "LoginClient",
    "AsyncLoginClient",
    "IDTokenClaims",
    "IDTokenError",
    "LoginKeySourceError",
    "LoginService",
    "MiniAppsService",
    "AsyncLoginService",
    "AsyncMiniAppsService",
    "UserInfo",
    "LoginUserInfo",
    "MiniAppUserInfo",
    "MiniAppProfile",
    # Mini Apps merchant payments
    "payments",
    "PaymentsService",
    "AsyncPaymentsService",
    # OTP
    "OtpService",
    "AsyncOtpService",
    "Locale",
    "SendResponse",
    # Credentials & helpers
    "Credentials",
    "new_idempotency_key",
    # Options
    "RetryConfig",
    "DEFAULT_RETRY",
    "DEFAULT_TIMEOUT",
    # Errors
    "LinkError",
    "ConfigError",
    "ValidationError",
    "InvalidResponseError",
    "ConnectionError",
    "APIError",
    "AuthenticationError",
    "IdempotencyError",
    "RateLimitError",
    # Error guards
    "is_link_error",
    "is_api_error",
    "is_authentication_error",
    "is_idempotency_error",
    "is_rate_limit_error",
    "is_connection_error",
    "is_validation_error",
]
