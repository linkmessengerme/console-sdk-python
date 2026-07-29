"""Send an OTP with credentials from environment variables.

    export LINK_CLIENT_ID=lk_client_xxxxxxxx
    export LINK_PRIVATE_KEY="$(cat private_key.pem)"
    export LINK_API_BASE_URL=https://api.example.com
    python examples/send_otp.py +12025550123 123456
"""

from __future__ import annotations

import os
import sys

from link_console_sdk import ConsoleClient, LinkError


def main() -> int:
    phone = sys.argv[1] if len(sys.argv) > 1 else "+12025550123"
    code = sys.argv[2] if len(sys.argv) > 2 else "123456"

    with ConsoleClient(
        client_id=os.environ["LINK_CLIENT_ID"],
        private_key=os.environ["LINK_PRIVATE_KEY"],
        base_url=os.environ["LINK_API_BASE_URL"],
    ) as client:
        try:
            res = client.otp.send(phone=phone, code=code)
        except LinkError as err:
            print(f"send failed: {err}", file=sys.stderr)
            return 1

    print(f"request_id={res.request_id} status={res.status} locale_used={res.locale_used}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
