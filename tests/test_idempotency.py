from __future__ import annotations

import uuid

import pytest

from link_console_sdk import new_idempotency_key
from link_console_sdk._internal.idempotency import is_valid_idempotency_key


def test_new_key_is_uuid4_and_valid() -> None:
    key = new_idempotency_key()
    parsed = uuid.UUID(key)
    assert parsed.version == 4
    assert is_valid_idempotency_key(key)


def test_new_keys_are_unique() -> None:
    assert len({new_idempotency_key() for _ in range(100)}) == 100


@pytest.mark.parametrize("key", ["a", "order-42:otp", "A_b-C:1", "x" * 255])
def test_valid_keys(key: str) -> None:
    assert is_valid_idempotency_key(key)


@pytest.mark.parametrize("key", ["", "x" * 256, "has space", "emoji😀", "slash/here"])
def test_invalid_keys(key: str) -> None:
    assert not is_valid_idempotency_key(key)
