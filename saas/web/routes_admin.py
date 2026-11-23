"""Admin endpoints (docs/API.md §5). All routes require ``role=admin``.

This module is the aggregation entry point: the route tables of the domain
modules are merged into the single ``routes`` table that ``app.py`` registers.

* ``routes_admin_users``    – users, status/quota, user detail, encryption
* ``routes_admin_bots``     – templates, conf profiles, bots, bot content, appeals
* ``routes_admin_billing``  – overview, orders, ledger, redemption codes, usage
* ``routes_admin_settings`` – sandbox, health, logs, invites, audit, OAuth

Shared helpers live in ``admin_common``. Domain modules must not import this
module, which keeps the import graph acyclic.
"""

from __future__ import annotations

from aiohttp import web

from . import (
    routes_admin_billing,
    routes_admin_bots,
    routes_admin_settings,
    routes_admin_users,
)
from .admin_common import require_admin

__all__ = ["routes", "require_admin"]

_DOMAIN_MODULES = (
    routes_admin_users,
    routes_admin_bots,
    routes_admin_billing,
    routes_admin_settings,
)

routes = web.RouteTableDef()
for _module in _DOMAIN_MODULES:
    # RouteTableDef has no public bulk-add API; aiohttp keeps its entries in
    # ``_items`` (stable across 3.x), so merge them here once at import time.
    routes._items.extend(_module.routes._items)
