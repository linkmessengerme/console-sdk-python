"""Client options, retry policy and backoff computation."""

from __future__ import annotations

import random
from dataclasses import dataclass

from ._version import VERSION

#: Default per-request timeout, in seconds.
DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Automatic retry policy.

    Retries apply **only** to requests that carry an idempotency key (the SDK
    attaches one automatically) and only to transient failures — network errors,
    timeouts, ``408/429/5xx``, and the "request in progress" idempotency conflict.
    """

    #: Max retries after the first attempt. ``<= 0`` disables retries.
    max_retries: int = 2
    #: Initial backoff before the first retry, in seconds.
    initial_backoff: float = 0.1
    #: Upper bound on a single backoff, in seconds.
    max_backoff: float = 2.0


DEFAULT_RETRY = RetryConfig()

#: ``retry=`` accepts a :class:`RetryConfig`, ``None`` (defaults), or ``False``
#: (disabled).
RetryOption = "RetryConfig | bool | None"


def resolve_retry(retry: RetryConfig | bool | None) -> RetryConfig:
    if retry is False:
        return RetryConfig(
            max_retries=-1,
            initial_backoff=DEFAULT_RETRY.initial_backoff,
            max_backoff=DEFAULT_RETRY.max_backoff,
        )
    if retry is None or retry is True:
        return DEFAULT_RETRY
    return retry


def resolve_user_agent(suffix: str | None) -> str:
    base = f"link-console-sdk-python/{VERSION}"
    trimmed = (suffix or "").strip()
    return f"{base} {trimmed}" if trimmed else base


def compute_backoff(attempt: int, retry: RetryConfig) -> float:
    """Exponential backoff with full jitter on the upper half (matches Go/Node)."""
    base = retry.initial_backoff if retry.initial_backoff > 0 else 0.1
    ceiling = retry.max_backoff if retry.max_backoff > 0 else 2.0
    delay = base * (2 ** (attempt - 1))
    if delay > ceiling or delay <= 0:
        delay = ceiling
    half = delay / 2
    return float(half + random.random() * half)
