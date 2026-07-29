"""Local request validation — runs before anything leaves the process."""

from __future__ import annotations

import re

from .errors import ValidationError

# Phone: 8–15 digits, optional leading "+". Bare digits get a "+" prepended.
_PHONE_WITH_PLUS = re.compile(r"^\+[1-9][0-9]{7,14}$")
_PHONE_DIGITS = re.compile(r"^[1-9][0-9]{7,14}$")
# OTP code: 4–10 latin letters or digits.
_CODE = re.compile(r"^[A-Za-z0-9]{4,10}$")


def normalize_phone(phone: str) -> str:
    """Normalizes a phone to E.164 (``+`` prefix) or raises :class:`ValidationError`."""
    p = phone.strip()
    if _PHONE_WITH_PLUS.match(p):
        return p
    if _PHONE_DIGITS.match(p):
        return "+" + p
    raise ValidationError("phone must contain 8-15 digits and may start with +")


def validate_code(code: str) -> str:
    """Validates an OTP code and returns it trimmed, or raises :class:`ValidationError`."""
    c = code.strip()
    if not _CODE.match(c):
        raise ValidationError("code must be 4-10 latin letters or digits")
    return c
