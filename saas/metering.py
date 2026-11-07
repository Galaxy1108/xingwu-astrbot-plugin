"""Usage metering slice (M4): token pricing → usage record + ledger + quota.

``record_usage`` is the single write path for billable model traffic:

1. looks up the model profile's price (points per 1K input/output tokens),
2. computes ``points = ceil(in/1000*in_price + out/1000*out_price)``,
3. (optionally) enforces the prepaid wallet balance,
4. atomically writes ``usage_records`` + a ``consume`` ledger row + the cached
   ``wallets.balance`` and ``quotas.used_tokens`` counters,
5. audits ``usage.recorded``.

``usage_records.idem_key`` is unique: retries with the same key return the
existing row and never double-charge.  ``ledger`` is append-only, so the wallet
balance stays recomputable (``BillingService.reconcile``).
"""

from __future__ import annotations

import math
import sqlite3
from typing import Any

from .audit import AuditService
from .clock import Clock, SystemClock
from .db import Database
from .errors import Conflict, NotFound, ValidationError


class MeteringService:
    def __init__(
        self,
        db: Database,
        *,
        audit: AuditService | None = None,
        clock: Clock | None = None,
        settings_store: Any = None,
        catalog: Any = None,
    ) -> None:
        self.db = db
        self.audit = audit
        self.clock = clock or SystemClock()
        self.settings_store = settings_store
        self.catalog = catalog

    # -- pricing -------------------------------------------------------
    def model_price(self, model_id: str) -> dict[str, Any]:
        """Return the priced model row; unknown ids are a validation error."""
        row = self.db.query_one(
            "SELECT id, name, model, points_per_1k_input, points_per_1k_output, "
            "enabled FROM model_profiles WHERE id = ?",
            (model_id,),
        )
        if row is None:
            raise NotFound("模型不存在")
        return row

    @staticmethod
    def compute_points(
        tokens_in: int, tokens_out: int, in_price: float, out_price: float
    ) -> int:
        total = (int(tokens_in) / 1000.0) * float(in_price) + (
            int(tokens_out) / 1000.0
        ) * float(out_price)
        # Guard against tiny negative/NaN noise coming from float prices.
        if not math.isfinite(total) or total <= 0:
            return 0
        return int(math.ceil(total))

    # -- writes --------------------------------------------------------
    def record_usage(
        self,
        user_id: str,
        bot_id: str,
        model_id: str,
        tokens_in: int,
        tokens_out: int,
        ref: str = "",
        idem_key: str | None = None,
        *,
        actor_id: str = "",
        ip: str = "",
    ) -> dict[str, Any]:
        user_id = str(user_id or "").strip()
        if not user_id:
            raise ValidationError("user_id 不能为空", field="user_id")
        if self.db.query_one("SELECT id FROM users WHERE id = ?", (user_id,)) is None:
            raise NotFound("用户不存在")

        tokens_in = _tokens(tokens_in, "tokens_in")
        tokens_out = _tokens(tokens_out, "tokens_out")
        model = self.model_price(str(model_id or "").strip())
        points = self.compute_points(
            tokens_in,
            tokens_out,
            model.get("points_per_1k_input") or 0.0,
            model.get("points_per_1k_output") or 0.0,
        )
        idem = (idem_key or "").strip() or None
        if idem:
            existing = self.db.query_one(
                "SELECT * FROM usage_records WHERE idem_key = ?", (idem,)
            )
            if existing is not None:
                return self._result(existing, idempotent=True)

        balance = self.balance(user_id)
        if self._enforce_balance() and balance < points:
            raise Conflict(
                "点数余额不足",
                code="insufficient_balance",
                extra={"balance": balance, "points": points},
            )

        now = self.clock.now()
        ref = str(ref or "")
        bot_id = str(bot_id or "")
        try:
            with self.db.transaction():
                cursor = self.db.execute(
                    "INSERT INTO usage_records(user_id, bot_id, model_id, model_name, "
                    "tokens_in, tokens_out, points, ref, idem_key, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        user_id,
                        bot_id,
                        model["id"],
                        model.get("name", ""),
                        tokens_in,
                        tokens_out,
                        points,
                        ref,
                        idem,
                        now,
                    ),
                )
                usage_id = int(cursor.lastrowid or 0)
                self.db.execute(
                    "INSERT INTO ledger(user_id, delta, type, ref, idem_key, note, "
                    "created_at) VALUES (?,?,'consume',?,?,?,?)",
                    (
                        user_id,
                        -points,
                        f"usage:{usage_id}",
                        f"usage:{usage_id}",
                        f"模型用量 {model.get('name') or model['id']}",
                        now,
                    ),
                )
                self.db.execute(
                    "INSERT INTO wallets(user_id, balance) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance",
                    (user_id, -points),
                )
                self.db.execute(
                    "INSERT INTO quotas(user_id, used_tokens, period_start) VALUES (?,?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "used_tokens = used_tokens + excluded.used_tokens",
                    (user_id, tokens_in + tokens_out, now),
                )
        except sqlite3.IntegrityError:
            if idem:
                existing = self.db.query_one(
                    "SELECT * FROM usage_records WHERE idem_key = ?", (idem,)
                )
                if existing is not None:
                    return self._result(existing, idempotent=True)
            raise Conflict("用量记录冲突，请重试") from None

        usage = self.db.query_one(
            "SELECT * FROM usage_records WHERE id = ?", (usage_id,)
        )
        self._audit(
            actor_id=actor_id,
            ip=ip,
            user_id=user_id,
            bot_id=bot_id,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            points=points,
            usage_id=usage_id,
            ref=ref,
        )
        return self._result(usage, idempotent=False)

    # -- reads ---------------------------------------------------------
    def usage_list(
        self,
        user_id: str | None = None,
        *,
        page: int = 1,
        page_size: int = 20,
        days: int | None = None,
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        where: list[str] = []
        params: list[Any] = []
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
        if days:
            where.append("created_at >= ?")
            params.append(self.clock.now() - max(1, int(days)) * 86400)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = int(
            self.db.scalar(
                f"SELECT COUNT(*) AS c FROM usage_records {clause}", params, 0
            )
        )
        rows = self.db.query(
            "SELECT id, user_id, bot_id, model_id, model_name, tokens_in, tokens_out, "
            f"points, ref, created_at FROM usage_records {clause} "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
        return {"items": rows, "total": total, "page": page, "page_size": page_size}

    def usage_summary(self, user_id: str, *, days: int = 30) -> dict[str, Any]:
        days = max(1, min(366, int(days)))
        now = self.clock.now()
        since = now - days * 86400
        row = self.db.query_one(
            "SELECT COALESCE(SUM(tokens_in),0) AS tokens_in, "
            "COALESCE(SUM(tokens_out),0) AS tokens_out, "
            "COALESCE(SUM(points),0) AS points, "
            "COUNT(*) AS records "
            "FROM usage_records WHERE user_id = ? AND created_at >= ?",
            (user_id, since),
        ) or {}
        tokens_in = int(row.get("tokens_in") or 0)
        tokens_out = int(row.get("tokens_out") or 0)
        return {
            "user_id": user_id,
            "days": days,
            "since": since,
            "until": now,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens": tokens_in + tokens_out,
            "points": int(row.get("points") or 0),
            "records": int(row.get("records") or 0),
        }

    def balance(self, user_id: str) -> int:
        return int(
            self.db.scalar(
                "SELECT balance FROM wallets WHERE user_id = ?", (user_id,), 0
            )
            or 0
        )

    # -- helpers -------------------------------------------------------
    def _enforce_balance(self) -> bool:
        if self.settings_store is None:
            return False
        try:
            value = self.settings_store.get("billing.enforce_balance", None)
            if value is None:
                billing = self.settings_store.get("billing", None)
                if isinstance(billing, dict):
                    value = billing.get("enforce_balance")
        except Exception:  # noqa: BLE001 - settings must never break billing
            return False
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _result(self, usage: dict[str, Any] | None, *, idempotent: bool) -> dict[str, Any]:
        usage = dict(usage or {})
        return {
            "usage": usage,
            "points": int(usage.get("points") or 0),
            "idempotent": idempotent,
            "balance": self.balance(usage.get("user_id", "")),
        }

    def _audit(
        self,
        *,
        actor_id: str,
        ip: str,
        user_id: str,
        bot_id: str,
        model: dict[str, Any],
        tokens_in: int,
        tokens_out: int,
        points: int,
        usage_id: int,
        ref: str,
    ) -> None:
        if self.audit is None:
            return
        self.audit.log(
            actor_id=actor_id,
            actor_role="admin" if actor_id else "system",
            action="usage.recorded",
            target_type="usage",
            target_id=str(usage_id),
            ip=ip,
            detail={
                "user_id": user_id,
                "bot_id": bot_id,
                "model_id": model.get("id", ""),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "points": points,
                "ref": ref,
            },
        )


def _tokens(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{field} 必须是非负整数", field=field)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} 必须是非负整数", field=field) from None
    if number < 0:
        raise ValidationError(f"{field} 必须是非负整数", field=field)
    return number
