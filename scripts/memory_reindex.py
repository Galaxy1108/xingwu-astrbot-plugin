#!/usr/bin/env python3
"""Backfill the per-bot vector index for existing memories.

Usage::

    ../AstrBot/.venv/bin/python scripts/memory_reindex.py --data-dir devdata

Embedding must be enabled in admin settings (`/admin/settings`): the script
reads the same encrypted platform settings and uses the configured API.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from saas.config import Settings  # noqa: E402
from saas.container import Container  # noqa: E402


async def run(args: argparse.Namespace) -> int:
    settings = Settings.from_env(args.data_dir)
    container = Container(settings)
    try:
        if args.bot:
            bots = [
                row
                for row in container.db.query(
                    "SELECT id, name FROM bots WHERE id = ?", (args.bot,)
                )
            ]
        else:
            bots = container.db.query(
                "SELECT id, name FROM bots WHERE status != 'deleted' ORDER BY created_at"
            )
        if not bots:
            print("没有可处理的 Bot")
            return 0
        failed = 0
        for bot in bots:
            result = await container.memory_service.reindex_bot(
                bot["id"], batch_size=args.batch_size
            )
            if result.get("ok"):
                print(
                    f"[ok] {bot['name']} ({bot['id']}): "
                    f"{result.get('indexed', 0)}/{result.get('total', 0)} vectors"
                )
            else:
                failed += 1
                print(f"[skip] {bot['name']} ({bot['id']}): {result.get('reason')}")
        await container.memory_service.wait_for_vector_tasks()
        return 1 if failed == len(bots) else 0
    finally:
        container.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="devdata")
    parser.add_argument("--bot", default="", help="只处理指定 bot_id")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
