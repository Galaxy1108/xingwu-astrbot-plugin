#!/usr/bin/env python3
"""Test-only harness: a real console server with an injectable AstrBot port.

Used by ``api_acceptance.py`` (check B5) to prove that a *mid-creation* failure
(persona / config / route / platform step) rolls back every side effect:
framework state, the ``bots`` row and the per-bot SQLCipher memory file.

This file lives under ``tests/e2e/`` on purpose: it does not touch production
code, it only imports it. It exposes two extra endpoints that a real server
never has:

    GET  /__test__/state     -> FakeAstrBot state + DB rows + memory dir listing
    POST /__test__/fail_on   -> {"steps": ["create_platform", ...]}

The server prints one JSON line when ready::

    {"ready": true, "port": 12345, "invite": "INV-...", "data_dir": "..."}

Usage::

    <venv-python> tests/e2e/rollback_harness.py --port 0 --data-dir /tmp/qa
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiohttp import web  # noqa: E402

from saas.config import Settings  # noqa: E402
from saas.container import Container  # noqa: E402
from saas.fake_astrbot import FakeAstrBot  # noqa: E402
from saas.web.app import create_app, ok  # noqa: E402

FAILABLE_STEPS = (
    "create_persona",
    "create_config",
    "bind_route",
    "create_platform",
)


async def serve(args: argparse.Namespace) -> None:
    settings = Settings.for_dev(args.data_dir)
    settings.port = args.port
    port = FakeAstrBot()
    container = Container(settings, port=port)
    container.seed_defaults()
    invite = container.create_invite(admin_id="system", max_uses=50)

    app = create_app(container)

    async def test_state(request: web.Request) -> web.Response:
        memory = sorted(p.name for p in settings.memory_dir.iterdir())
        return ok(
            {
                "fake": {
                    "personas": sorted(port.state.personas),
                    "configs": sorted(port.state.configs),
                    "routes": dict(port.state.routes),
                    "platforms": sorted(port.state.platforms),
                },
                "bots": container.db.query(
                    "SELECT id, name, status, memory_db FROM bots ORDER BY created_at"
                ),
                "bindings": container.db.query("SELECT bot_id FROM bot_bindings"),
                "memory": memory,
                "fail_on": sorted(port.fail_on),
            }
        )

    async def test_fail_on(request: web.Request) -> web.Response:
        body = await request.json()
        steps = body.get("steps") or []
        unknown = [step for step in steps if step not in FAILABLE_STEPS]
        if unknown:
            return web.json_response(
                {"ok": False, "error": {"code": "validation_error", "message": str(unknown)}},
                status=400,
            )
        port.fail_on = set(steps)
        return ok({"fail_on": sorted(port.fail_on)})

    async def test_reset(request: web.Request) -> web.Response:
        """Delete every bot row / memory file (between rollback scenarios)."""
        for row in container.db.query("SELECT id FROM bots"):
            container.qr.cancel(row["id"])
            try:
                container.memory_storage.delete_library(row["id"])
            except Exception:  # noqa: BLE001
                pass
        container.db.execute("DELETE FROM bot_bindings")
        container.db.execute("DELETE FROM bots")
        port.state.personas.clear()
        port.state.configs.clear()
        port.state.routes.clear()
        port.state.platforms.clear()
        port._qr.clear()
        port._credentials.clear()
        port._scanned.clear()
        port.fail_on.clear()
        return ok({"reset": True})

    app.router.add_get("/__test__/state", test_state)
    app.router.add_post("/__test__/fail_on", test_fail_on)
    app.router.add_post("/__test__/reset", test_reset)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, settings.host, settings.port)
    await site.start()
    print(
        json.dumps(
            {
                "ready": True,
                "port": settings.port,
                "host": settings.host,
                "invite": invite["code"],
                "data_dir": str(settings.data_dir),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        container.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    asyncio.run(serve(args))


if __name__ == "__main__":
    main()
