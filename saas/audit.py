"""Audit trail service (append-only)."""

from __future__ import annotations

import json
from typing import Any

from .clock import Clock, SystemClock
from .db import Database


class AuditService:
    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self.db = db
        self.clock = clock or SystemClock()

    def log(
        self,
        *,
        actor_id: str = "",
        actor_role: str = "",
        action: str,
        target_type: str = "",
        target_id: str = "",
        ip: str = "",
        reason: str = "",
        detail: dict[str, Any] | str | None = None,
    ) -> int:
        if isinstance(detail, dict):
            detail_text = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
        else:
            detail_text = detail or ""
        cursor = self.db.execute(
            "INSERT INTO audit_logs(actor_id, actor_role, action, target_type, "
            "target_id, ip, reason, detail, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                actor_id,
                actor_role,
                action,
                target_type,
                target_id,
                ip,
                reason,
                detail_text,
                self.clock.now(),
            ),
        )
        return int(cursor.lastrowid or 0)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        action: str | None = None,
        actor_id: str | None = None,
        target_id: str | None = None,
    ) -> dict[str, Any]:
        where: list[str] = []
        params: list[Any] = []
        if action:
            where.append("action = ?")
            params.append(action)
        if actor_id:
            where.append("actor_id = ?")
            params.append(actor_id)
        if target_id:
            where.append("target_id = ?")
            params.append(target_id)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = int(
            self.db.scalar(f"SELECT COUNT(*) AS c FROM audit_logs {clause}", params, 0)
        )
        rows = self.db.query(
            f"SELECT * FROM audit_logs {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
        for row in rows:
            detail = row.get("detail") or ""
            if detail:
                try:
                    row["detail"] = json.loads(detail)
                except (TypeError, ValueError):
                    pass
        return {"items": rows, "total": total, "page": page, "page_size": page_size}

    def access_log(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        bot_id: str | None = None,
        user_id: str | None = None,
        admin_id: str | None = None,
    ) -> dict[str, Any]:
        where: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("bot_id", bot_id),
            ("user_id", user_id),
            ("admin_id", admin_id),
        ):
            if value:
                where.append(f"{column} = ?")
                params.append(value)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = int(
            self.db.scalar(
                f"SELECT COUNT(*) AS c FROM content_access_logs {clause}", params, 0
            )
        )
        rows = self.db.query(
            f"SELECT * FROM content_access_logs {clause} "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
        return {"items": rows, "total": total, "page": page, "page_size": page_size}
