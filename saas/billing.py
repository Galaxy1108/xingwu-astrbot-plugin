"""Billing slice of M3: manual credit orders + append-only ledger.

Design rules (handoff §4.8 / §5):
- ``ledger`` is append-only; balance is a cache that can always be recomputed.
- ``orders.external_ref`` and ``ledger.idem_key`` are unique → double confirms
  and duplicate manual adjustments are rejected instead of double-crediting.
- Every admin action is audited.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .audit import AuditService
from .clock import Clock, SystemClock
from .db import Database
from .errors import AppError, Conflict, NotFound, ValidationError
from .security import random_id


class BillingService:
    def __init__(
        self, db: Database, *, audit: AuditService, clock: Clock | None = None
    ) -> None:
        self.db = db
        self.audit = audit
        self.clock = clock or SystemClock()

    # -- reads ---------------------------------------------------------
    def balance(self, user_id: str) -> int:
        row = self.db.query_one("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
        if row is None:
            return 0
        return int(row["balance"])

    def recompute_balance(self, user_id: str) -> int:
        return int(
            self.db.scalar(
                "SELECT COALESCE(SUM(delta), 0) AS total FROM ledger WHERE user_id = ?",
                (user_id,),
                default=0,
            )
        )

    def ledger(
        self, user_id: str, *, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        total = int(
            self.db.scalar(
                "SELECT COUNT(*) AS c FROM ledger WHERE user_id = ?", (user_id,), 0
            )
        )
        items = self.db.query(
            "SELECT id, delta, type, ref, note, created_at FROM ledger "
            "WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (user_id, page_size, (page - 1) * page_size),
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def orders(self, *, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        total = int(self.db.scalar("SELECT COUNT(*) AS c FROM orders", (), 0))
        items = self.db.query(
            "SELECT o.*, u.email AS user_email FROM orders o "
            "LEFT JOIN users u ON u.id = o.user_id "
            "ORDER BY o.created_at DESC LIMIT ? OFFSET ?",
            (page_size, (page - 1) * page_size),
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    # -- writes --------------------------------------------------------
    def create_order(
        self,
        *,
        admin_id: str,
        user_id: str,
        credits: int,
        amount_cny: float = 0.0,
        external_ref: str | None = None,
        note: str = "",
        ip: str = "",
    ) -> dict[str, Any]:
        credits = int(credits)
        if credits == 0:
            raise ValidationError("credits 不能为 0", field="credits")
        if self.db.query_one("SELECT id FROM users WHERE id = ?", (user_id,)) is None:
            raise NotFound("用户不存在")
        external_ref = (external_ref or "").strip() or None
        if external_ref:
            existing = self.db.query_one(
                "SELECT * FROM orders WHERE external_ref = ?", (external_ref,)
            )
            if existing is not None:
                return {"order": existing, "idempotent": True}
        order_id = random_id("o", 8)
        now = self.clock.now()
        try:
            self.db.execute(
                "INSERT INTO orders(id, user_id, amount_cny, credits, source, "
                "external_ref, status, created_at, paid_at, operator) "
                "VALUES (?,?,?,?,'manual',?,'pending',?,0,?)",
                (order_id, user_id, float(amount_cny or 0), credits, external_ref, now, admin_id),
            )
        except sqlite3.IntegrityError:
            existing = self.db.query_one(
                "SELECT * FROM orders WHERE external_ref = ?", (external_ref,)
            )
            if existing is None:
                raise Conflict("订单号冲突，请重试") from None
            return {"order": existing, "idempotent": True}
        self.audit.log(
            actor_id=admin_id,
            actor_role="admin",
            action="order.created",
            target_type="order",
            target_id=order_id,
            ip=ip,
            reason=note,
            detail={"user_id": user_id, "credits": credits, "amount_cny": amount_cny},
        )
        return {
            "order": self.db.query_one("SELECT * FROM orders WHERE id = ?", (order_id,)),
            "idempotent": False,
        }

    def confirm_order(
        self, *, order_id: str, admin_id: str, ip: str = ""
    ) -> dict[str, Any]:
        order = self.db.query_one("SELECT * FROM orders WHERE id = ?", (order_id,))
        if order is None:
            raise NotFound("订单不存在")
        if order["status"] == "paid":
            return {"order": order, "already_paid": True}
        if order["status"] != "pending":
            raise Conflict("订单状态不允许确认", code="conflict")
        now = self.clock.now()
        with self.db.transaction():
            try:
                self.db.execute(
                    "INSERT INTO ledger(user_id, delta, type, ref, idem_key, note, created_at) "
                    "VALUES (?,?,'grant',?,?,?,?)",
                    (
                        order["user_id"],
                        int(order["credits"]),
                        f"order:{order_id}",
                        f"order:{order_id}",
                        f"手动充值 {order_id}",
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                # Ledger already has this grant: treat as idempotent success.
                pass
            else:
                self.db.execute(
                    "INSERT INTO wallets(user_id, balance) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance",
                    (order["user_id"], int(order["credits"])),
                )
            self.db.execute(
                "UPDATE orders SET status = 'paid', paid_at = ?, operator = ? WHERE id = ?",
                (now, admin_id, order_id),
            )
        self.audit.log(
            actor_id=admin_id,
            actor_role="admin",
            action="order.confirmed",
            target_type="order",
            target_id=order_id,
            ip=ip,
            detail={"user_id": order["user_id"], "credits": order["credits"]},
        )
        return {
            "order": self.db.query_one("SELECT * FROM orders WHERE id = ?", (order_id,)),
            "already_paid": False,
        }

    def adjust(
        self,
        *,
        admin_id: str,
        user_id: str,
        delta: int,
        reason: str = "",
        idem_key: str | None = None,
        ip: str = "",
    ) -> dict[str, Any]:
        delta = int(delta)
        if delta == 0:
            raise ValidationError("delta 不能为 0", field="delta")
        if self.db.query_one("SELECT id FROM users WHERE id = ?", (user_id,)) is None:
            raise NotFound("用户不存在")
        idem = (idem_key or "").strip() or None
        if idem:
            existing = self.db.query_one(
                "SELECT * FROM ledger WHERE idem_key = ?", (idem,)
            )
            if existing is not None:
                return {"ledger": existing, "idempotent": True, "balance": self.balance(user_id)}
        now = self.clock.now()
        try:
            with self.db.transaction():
                cursor = self.db.execute(
                    "INSERT INTO ledger(user_id, delta, type, ref, idem_key, note, created_at) "
                    "VALUES (?,?,'adjust','',?,?,?)",
                    (user_id, delta, idem, reason, now),
                )
                self.db.execute(
                    "INSERT INTO wallets(user_id, balance) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance",
                    (user_id, delta),
                )
                ledger_id = int(cursor.lastrowid or 0)
        except sqlite3.IntegrityError:
            existing = self.db.query_one(
                "SELECT * FROM ledger WHERE idem_key = ?", (idem,)
            )
            if existing is None:
                raise Conflict("幂等键冲突，请重试") from None
            return {"ledger": existing, "idempotent": True, "balance": self.balance(user_id)}
        self.audit.log(
            actor_id=admin_id,
            actor_role="admin",
            action="wallet.adjusted",
            target_type="user",
            target_id=user_id,
            ip=ip,
            reason=reason,
            detail={"delta": delta, "idem_key": idem},
        )
        return {
            "ledger": self.db.query_one("SELECT * FROM ledger WHERE id = ?", (ledger_id,)),
            "idempotent": False,
            "balance": self.balance(user_id),
        }

    def reconcile(self, user_id: str) -> dict[str, Any]:
        """Repair the cached wallet balance from the append-only ledger."""
        expected = self.recompute_balance(user_id)
        self.db.execute(
            "INSERT INTO wallets(user_id, balance) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET balance = excluded.balance",
            (user_id, expected),
        )
        return {"user_id": user_id, "balance": expected}
