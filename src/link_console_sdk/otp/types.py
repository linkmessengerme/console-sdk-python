"""Public OTP request/response types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Locale(str, Enum):
    """Supported message locales (ISO 639-1).

    When ``locale`` is omitted on a send, the gateway auto-detects it from the
    phone's country code. Any ISO 639-1 string the platform supports is also
    accepted directly.
    """

    RUSSIAN = "ru"
    ENGLISH = "en"
    KAZAKH = "kk"
    UZBEK = "uz"

    def __str__(self) -> str:  # so f-strings/logging show "ru", not "Locale.RUSSIAN"
        return self.value


@dataclass(frozen=True, slots=True)
class SendResponse:
    """Result of an OTP send."""

    request_id: str
    phone: str
    status: str
    #: Template that rendered the message: a template id, or ``"fallback"``.
    template_used: str | None = None
    #: Locale actually used after auto-detect/fallback resolution.
    locale_used: str | None = None
