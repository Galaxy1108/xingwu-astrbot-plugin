#!/usr/bin/env python3
"""Seed an admin account / demo templates / invite code (idempotent).

Works in both standalone (FakeAstrBot) and real deployments (same data dir).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from saas.config import Settings  # noqa: E402
from saas.container import Container  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="devdata")
    parser.add_argument("--email", default="admin@example.com")
    parser.add_argument("--role", default="admin", choices=["admin", "user"])
    parser.add_argument("--no-templates", dest="templates", action="store_false")
    parser.add_argument(
        "--invite", action="store_true", help="create and print a one-time invite"
    )
    args = parser.parse_args()

    settings = Settings.for_dev(args.data_dir)
    container = Container(settings)
    result = container.seed_defaults(admin_email=args.email, templates=args.templates)
    print("seed:", result)
    if args.invite:
        invite = container.create_invite(admin_id="seed", max_uses=1)
        print("invite:", invite["code"], "expires_at:", invite["expires_at"])
    print("data dir:", settings.data_dir)
    container.close()


if __name__ == "__main__":
    main()
