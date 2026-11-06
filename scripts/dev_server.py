#!/usr/bin/env python3
"""Standalone dev server: FakeAstrBot + SQLCipher + seeded admin/templates.

Usage::

    uv run --python ../AstrBot/.venv/bin/python scripts/dev_server.py \
        --data-dir devdata --port 6180

or simply::

    ../AstrBot/.venv/bin/python scripts/dev_server.py

The console is served at http://127.0.0.1:6180/console/ (after `npm run build`).
OTP codes are echoed in API responses because ``otp_dev_echo`` is enabled.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiohttp import web  # noqa: E402

from saas.config import Settings  # noqa: E402
from saas.container import Container  # noqa: E402
from saas.fake_astrbot import FakeAstrBot  # noqa: E402
from saas.web.app import create_app  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def serve(args: argparse.Namespace) -> None:
    if args.data_dir:
        settings = Settings.for_dev(args.data_dir)
    else:
        settings = Settings.from_env()
        if args.dev:
            settings = Settings.for_dev(settings.data_dir)
    settings.port = args.port
    container = Container(settings, port=FakeAstrBot())
    if args.seed:
        container.seed_defaults()
        invite = container.create_invite(admin_id="system", max_uses=1)
        print("=" * 72)
        print(f"  控制台：http://{settings.host}:{settings.port}/console/")
        print(f"  管理员：{settings.admin_email}（OTP 登录，验证码见接口返回 dev_code）")
        print(f"  邀请码：{invite['code']}")
        print(f"  数据目录：{settings.data_dir}")
        print("=" * 72)
    app = create_app(container)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, settings.host, settings.port)
    await site.start()
    print(f"API 已启动：http://{settings.host}:{settings.port}/api/version")
    stop = asyncio.Event()
    try:
        await stop.wait()
    finally:
        await runner.cleanup()
        container.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="devdata")
    parser.add_argument("--port", type=int, default=6180)
    parser.add_argument("--dev", action="store_true", default=True)
    parser.add_argument("--no-seed", dest="seed", action="store_false")
    args = parser.parse_args()
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
