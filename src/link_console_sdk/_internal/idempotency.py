"""Idempotency-key generation and validation."""

from __future__ import annotations

import re
import uuid

# Idempotency key charset accepted by the gateway: 1–255 of [A-Za-z0-9_-:].
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-:]{1,255}$")


def new_idempotency_key() -> str:
    """Generates a fresh idempotency key (UUID v4)."""
    return str(uuid.uuid4())


def is_valid_idempotency_key(key: str) -> bool:
    return bool(_KEY_RE.match(key.strip()))
