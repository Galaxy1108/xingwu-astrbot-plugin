"""Redemption codes (M5): no-payment top-ups via admin-issued codes.

Product rule: the platform does not take payments; admins generate batched
redemption codes and users redeem them for prepaid points.  A redemption is
always ledger-first (append-only ``ledger`` row + cached ``wallets.balance``),
exactly like manual grants in :mod:`saas.billing`, so the balance stays
recomputable with ``BillingService.reconcile``.

Invariants:

* ``redemption_codes.code`` is globally unique; the plaintext code is the
  bearer secret (shown to admins once in the generate response).
* ``redemption_uses`` PK ``(code_id, user_id)`` makes "one code, one user"
  true even when ``max_uses > 1``.
* Redeem runs inside ``BEGIN IMMEDIATE`` so two concurrent requests cannot
  overshoot ``max_uses`` or double-grant the same user.
"""

from __future__ import annotations

import secrets
import sqlite3
from typing import Any

from .audit import AuditService
from .clock import Clock, SystemClock
from .db import Database
from .errors import AppError, Conflict, NotFound, ValidationError

# Ambiguous glyphs (I/O/0/1) are removed so codes can be typed/copied safely.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_PREFIX = "SAAS"
CODE_GROUPS = 2
CODE_GROUP_LEN = 4
MAX_GENERATE_COUNT = 100
MAX_USES_LIMIT = 1000

# list_codes status filter → SQL fragment.
_STATUS_FILTERS = {
    "active": "disabled = 0 AND used_count < max_uses AND (expires_at = 0 OR expires_at > ?)",
    "available": "disabled = 0 AND used_count < max_uses AND (expires_at = 0 OR expires_at > ?)",
    "unused": "disabled = 0 AND used_count < max_uses AND (expires_at = 0 OR expires_at > ?)",
    "used": "used_count >= max_uses",
    "exhausted": "used_count >= max_uses",
    "expired": "expires_at > 0 AND expires_at <= ?",
    "disabled": "disabled = 1",
    "revoked": "disabled = 1",
}


def _new_code() -> str:
    chunks = [
        "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_GROUP_LEN))
        for _ in range(CODE_GROUPS)
    ]
    return f"{CODE_PREFIX}-" + "-".join(chunks)


def normalize_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _int_value(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{field} 必须是整数", field=field)
    if isinstance(value, float):
        if not value.is_integer():
            raise ValidationError(f"{field} 必须是整数", field=field)
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} 必须是整数", field=field) from None


def _bounded_int(value: Any, field: str, low: int, high: int) -> int:
    number = _int_value(value, field)
    if number < low or number > high:
        raise ValidationError(f"{field} 必须在 {low}–{high} 之间", field=field)
    return number


class RedemptionService:
    def __init__(
        self,
        db: Database,
        *,
        audit: AuditService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.db = db
        self.audit = audit
        self.clock = clock or SystemClock()

    # -- serialisation -------------------------------------------------
    def serialize(self, row: dict[str, Any], *, now: int | None = None) -> dict[str, Any]:
        now = self.clock.now() if now is None else int(now)
        points = int(row.get("points") or 0)
        max_uses = int(row.get("max_uses") or 1)
        used_count = int(row.get("used_count") or 0)
        expires_at = int(row.get("expires_at") or 0)
        disabled = bool(row.get("disabled"))
        if disabled:
            status = "disabled"
        elif expires_at and expires_at <= now:
            status = "expired"
        elif used_count >= max_uses:
            status = "used"
        else:
            status = "active"
        return {
            "id": row["id"],
            "code": row["code"],
            "points": points,
            # ``credits`` is the legacy/console name for the same value.
            "credits": points,
            "note": row.get("note", "") or "",
            "max_uses": max_uses,
            "used_count": used_count,
            "remaining": max(0, max_uses - used_count),
            "expires_at": expires_at,
            "disabled": disabled,
            "status": status,
            "created_by": row.get("created_by", "") or "",
            "created_at": int(row.get("created_at") or 0),
        }

    def get(self, identifier: str) -> dict[str, Any]:
        return self.serialize(self._row(identifier))

    def _row(self, identifier: str) -> dict[str, Any]:
        value = str(identifier or "").strip()
        row = self.db.query_one(
            "SELECT * FROM redemption_codes WHERE id = ? OR code = ?",
            (value, normalize_code(value)),
        )
        if row is None:
            raise NotFound("兑换码不存在")
        return row

    # -- admin: generate / list / disable ------------------------------
    def generate(
        self,
        points: Any,
        note: str = "",
        count: Any = 1,
        max_uses: Any = 1,
        expires_at: Any = None,
        actor: str = "",
        ip: str = "",
    ) -> list[dict[str, Any]]:
        points = _bounded_int(points, "points", 1, 1_000_000_000)
        count = _bounded_int(count, "count", 1, MAX_GENERATE_COUNT)
        max_uses = _bounded_int(max_uses, "max_uses", 1, MAX_USES_LIMIT)
        if expires_at is None or expires_at == "":
            expires_value = 0
        else:
            expires_value = _int_value(expires_at, "expires_at")
            if expires_value < 0:
                raise ValidationError("expires_at 不能为负数", field="expires_at")
        note = str(note or "")[:500]
        now = self.clock.now()
        created: list[dict[str, Any]] = []
        with self.db.transaction():
            for _ in range(count):
                row = self._insert_code(
                    points=points,
                    note=note,
                    max_uses=max_uses,
                    expires_at=expires_value,
                    actor=actor,
                    now=now,
                )
                created.append(self.serialize(row, now=now))
        self._audit(
            actor_id=actor,
            ip=ip,
            action="redemption.generated",
            target_type="redemption_code",
            target_id="",
            detail={
                "count": len(created),
                "points": points,
                "max_uses": max_uses,
                "expires_at": expires_value,
                "ids": [item["id"] for item in created],
            },
        )
        return created

    def _insert_code(
        self,
        *,
        points: int,
        note: str,
        max_uses: int,
        expires_at: int,
        actor: str,
        now: int,
    ) -> dict[str, Any]:
        last_error: sqlite3.IntegrityError | None = None
        for _ in range(50):
            code_id = "rc_" + secrets.token_hex(8)
            code = _new_code()
            try:
                self.db.execute(
                    "INSERT INTO redemption_codes(id, code, points, note, max_uses, "
                    "used_count, expires_at, disabled, created_by, created_at) "
                    "VALUES (?,?,?,?,?,0,?,0,?,?)",
                    (code_id, code, points, note, max_uses, expires_at, actor, now),
                )
            except sqlite3.IntegrityError as exc:  # pragma: no cover - 32^8 space
                last_error = exc
                continue
            return self.db.query_one(
                "SELECT * FROM redemption_codes WHERE id = ?", (code_id,)
            ) or {}
        raise Conflict("兑换码生成冲突，请重试") from last_error

    def list_codes(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        now = self.clock.now()
        raw_status = str(status or "").strip().lower()
        where = ""
        params: list[Any] = []
        if raw_status and raw_status != "all":
            fragment = _STATUS_FILTERS.get(raw_status)
            if fragment is None:
                raise ValidationError(
                    f"status 不合法：{raw_status}", field="status"
                )
            where = f"WHERE {fragment}"
            if "?" in fragment:
                params.append(now)
        total = int(
            self.db.scalar(
                f"SELECT COUNT(*) AS c FROM redemption_codes {where}", params, 0
            )
        )
        rows = self.db.query(
            f"SELECT * FROM redemption_codes {where} "
            "ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
        return {
            "items": [self.serialize(row, now=now) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def set_disabled(
        self,
        identifier: str,
        disabled: bool = True,
        *,
        actor_id: str = "",
        ip: str = "",
    ) -> dict[str, Any]:
        row = self._row(identifier)
        self.db.execute(
            "UPDATE redemption_codes SET disabled = ? WHERE id = ?",
            (1 if disabled else 0, row["id"]),
        )
        self._audit(
            actor_id=actor_id,
            ip=ip,
            action="redemption.disabled" if disabled else "redemption.enabled",
            target_type="redemption_code",
            target_id=row["id"],
            detail={"code": row["code"], "disabled": bool(disabled)},
        )
        return self.serialize(
            self.db.query_one(
                "SELECT * FROM redemption_codes WHERE id = ?", (row["id"],)
            )
            or row
        )

    def disable(
        self, identifier: str, *, actor_id: str = "", ip: str = ""
    ) -> dict[str, Any]:
        return self.set_disabled(identifier, True, actor_id=actor_id, ip=ip)

    # -- user: redeem --------------------------------------------------
    def redeem(
        self,
        user_id: str,
        code: str,
        *,
        ip: str = "",
        actor_id: str = "",
    ) -> dict[str, Any]:
        normalized = normalize_code(code)
        if not normalized:
            raise ValidationError("请输入兑换码", field="code")
        user_id = str(user_id or "").strip()
        user = self.db.query_one(
            "SELECT id FROM users WHERE id = ? AND status != 'deleted'", (user_id,)
        )
        if user is None:
            raise NotFound("用户不存在")
        now = self.clock.now()
        try:
            row = self._redeem_transaction(user_id, normalized, now)
        except sqlite3.IntegrityError:
            # Ledger/use row race: both callers already passed the lookups.
            raise Conflict(
                "您已兑换过该兑换码，不能重复兑换", code="already_redeemed"
            ) from None
        balance = self.balance(user_id)
        points = int(row["points"])
        self._audit(
            actor_id=actor_id or user_id,
            ip=ip,
            action="redemption.redeemed",
            target_type="redemption_code",
            target_id=row["id"],
            detail={
                "code": row["code"],
                "user_id": user_id,
                "points": points,
                "balance": balance,
                "max_uses": int(row.get("max_uses") or 1),
                "used_count": int(row.get("used_count") or 0) + 1,
            },
            actor_role="user",
        )
        return {
            "code": row["code"],
            "points": points,
            # legacy alias used by the console
            "credits": points,
            "balance": balance,
        }

    def _redeem_transaction(
        self, user_id: str, normalized: str, now: int
    ) -> dict[str, Any]:
        with self.db.transaction():
            row = self.db.query_one(
                "SELECT * FROM redemption_codes WHERE code = ?", (normalized,)
            )
            if row is None:
                raise AppError(
                    "兑换码无效，请检查后重试", code="invalid", status=400
                )
            if row.get("disabled"):
                raise AppError(
                    "兑换码已被禁用，请联系管理员", code="disabled", status=400
                )
            expires_at = int(row.get("expires_at") or 0)
            if expires_at and expires_at <= now:
                raise AppError(
                    "兑换码已过期，请联系管理员重新发放",
                    code="expired",
                    status=410,
                )
            already = self.db.query_one(
                "SELECT 1 AS hit FROM redemption_uses WHERE code_id = ? AND user_id = ?",
                (row["id"], user_id),
            )
            if already is not None:
                raise Conflict(
                    "您已兑换过该兑换码，不能重复兑换", code="already_redeemed"
                )
            used_count = int(row.get("used_count") or 0)
            max_uses = int(row.get("max_uses") or 1)
            if used_count >= max_uses:
                raise AppError(
                    "兑换码已被用完，请联系管理员重新发放",
                    code="exhausted",
                    status=410,
                )
            try:
                self.db.execute(
                    "INSERT INTO redemption_uses(code_id, user_id, created_at) "
                    "VALUES (?,?,?)",
                    (row["id"], user_id, now),
                )
            except sqlite3.IntegrityError:
                raise Conflict(
                    "您已兑换过该兑换码，不能重复兑换", code="already_redeemed"
                ) from None
            self.db.execute(
                "UPDATE redemption_codes SET used_count = used_count + 1 WHERE id = ?",
                (row["id"],),
            )
            points = int(row["points"])
            self.db.execute(
                "INSERT INTO ledger(user_id, delta, type, ref, idem_key, note, "
                "created_at) VALUES (?,?,'grant',?,?,?,?)",
                (
                    user_id,
                    points,
                    f"redeem:{row['code']}",
                    f"redeem:{row['id']}:{user_id}",
                    f"兑换码入账 {row['code']}",
                    now,
                ),
            )
            self.db.execute(
                "INSERT INTO wallets(user_id, balance) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance",
                (user_id, points),
            )
            return row

    # -- reads ---------------------------------------------------------
    def balance(self, user_id: str) -> int:
        return int(
            self.db.scalar(
                "SELECT balance FROM wallets WHERE user_id = ?", (user_id,), 0
            )
            or 0
        )

    def recompute_balance(self, user_id: str) -> int:
        return int(
            self.db.scalar(
                "SELECT COALESCE(SUM(delta), 0) AS total FROM ledger WHERE user_id = ?",
                (user_id,),
                0,
            )
        )

    # -- helpers -------------------------------------------------------
    def _audit(
        self,
        *,
        actor_id: str,
        ip: str,
        action: str,
        target_type: str,
        target_id: str,
        detail: dict[str, Any],
        actor_role: str = "admin",
    ) -> None:
        if self.audit is None:
            return
        self.audit.log(
            actor_id=actor_id,
            actor_role=actor_role if actor_id else "system",
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            detail=detail,
        )
