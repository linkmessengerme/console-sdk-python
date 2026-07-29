from __future__ import annotations

import pytest

from link_console_sdk import ValidationError
from link_console_sdk.validation import normalize_phone, validate_code


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+12025550123", "+12025550123"),
        ("12025550123", "+12025550123"),
        ("  +12025550123  ", "+12025550123"),
        ("15551234567", "+15551234567"),
    ],
)
def test_normalize_phone_ok(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "12345", "+0123456789", "abc", "+1-202-555-0123", "0123456"])
def test_normalize_phone_invalid(raw: str) -> None:
    with pytest.raises(ValidationError):
        normalize_phone(raw)


@pytest.mark.parametrize("code", ["1234", "482913", "AB12cd", "0000000000"])
def test_validate_code_ok(code: str) -> None:
    assert validate_code(code) == code


@pytest.mark.parametrize("code", ["", "123", "12345678901", "12 34", "code!", "абвг"])
def test_validate_code_invalid(code: str) -> None:
    with pytest.raises(ValidationError):
        validate_code(code)
