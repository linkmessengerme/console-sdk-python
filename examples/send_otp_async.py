"""Send an OTP with the async client.

    python examples/send_otp_async.py link-oauth-client.json +12025550123 123456
"""

from __future__ import annotations

import asyncio
import sys

from link_console_sdk import AsyncConsoleClient, LinkError


async def main() -> int:
    key_path = sys.argv[1] if len(sys.argv) > 1 else "link-oauth-client.json"
    phone = sys.argv[2] if len(sys.argv) > 2 else "+12025550123"
    code = sys.argv[3] if len(sys.argv) > 3 else "123456"

    async with AsyncConsoleClient.from_key_file(key_path) as client:
        try:
            res = await client.otp.send(phone=phone, code=code)
        except LinkError as err:
            print(f"send failed: {err}", file=sys.stderr)
            return 1

    print(f"request_id={res.request_id} status={res.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
