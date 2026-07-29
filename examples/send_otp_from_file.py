"""Send an OTP using a downloaded key file.

    python examples/send_otp_from_file.py link-oauth-client.json +12025550123 123456
"""

from __future__ import annotations

import sys

from link_console_sdk import ConsoleClient, LinkError, Locale


def main() -> int:
    key_path = sys.argv[1] if len(sys.argv) > 1 else "link-oauth-client.json"
    phone = sys.argv[2] if len(sys.argv) > 2 else "+12025550123"
    code = sys.argv[3] if len(sys.argv) > 3 else "123456"

    with ConsoleClient.from_key_file(key_path) as client:
        try:
            res = client.otp.send(phone=phone, code=code, locale=Locale.ENGLISH)
        except LinkError as err:
            print(f"send failed: {err}", file=sys.stderr)
            return 1

    print(f"request_id={res.request_id} status={res.status} template_used={res.template_used}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
