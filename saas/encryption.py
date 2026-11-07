"""User-level encryption switch with resumable backfill job (handoff §6.10).

``decrypt`` = close the encryption for a user: conversations, memory libraries
and platform credentials are rewritten as plaintext. ``encrypt`` reverses it.
State machine: encrypted ↔ decrypting ↔ plaintext / encrypting, failures → paused.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .audit import AuditService
from .clock import Clock, SystemClock
from .db import Database
from .errors import AppError, Conflict, Forbidden, NotFound, ValidationError
from .security import random_id

logger = logging.getLogger(__name__)

ACTIVE_STATES = {"decrypting", "encrypting"}


class EncryptionService:
    def __init__(self, container) -> None:
        self.container = container
        self.db: Database = container.db
        self.clock: Clock = container.clock
        self.audit: AuditService = container.audit
        self._tasks: dict[str, asyncio.Task] = {}

    # -- status --------------------------------------------------------
    def status(self, user_id: str) -> dict[str, Any]:
        user = self.db.query_one(
            "SELECT encryption_enabled, encryption_state, encryption_changed_at "
            "FROM users WHERE id = ?",
            (user_id,),
        )
        if user is None:
            raise NotFound("用户不存在")
        job = self.db.query_one(
            "SELECT * FROM crypto_jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
        payload: dict[str, Any] = {
            "enabled": bool(user["encryption_enabled"]),
            "state": user["encryption_state"],
            "changed_at": int(user["encryption_changed_at"] or 0),
            "job": None,
        }
        if job is not None:
            total = int(job["total"] or 0)
            done = int(job["done"] or 0)
            payload["job"] = {
                "id": job["id"],
                "direction": job["direction"],
                "status": job["status"],
                "total": total,
                "done": done,
                "percent": int(done * 100 / total) if total else 0,
                "error": job["error"],
                "created_at": job["created_at"],
                "finished_at": job["finished_at"],
            }
        return payload

    # -- switch --------------------------------------------------------
    async def start(
        self,
        *,
        user_id: str,
        enabled: bool,
        actor_id: str,
        actor_role: str = "user",
        ip: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        user = self.db.query_one(
            "SELECT * FROM users WHERE id = ? AND status != 'deleted'", (user_id,)
        )
        if user is None:
            raise NotFound("用户不存在")
        if not enabled and actor_role == "admin":
            raise Forbidden("管理员不能关闭用户加密（只能强制开启）")
        if (
            not enabled
            and not self.container.settings.allow_user_disable_encryption
            and actor_role == "user"
        ):
            raise Forbidden("当前环境不允许用户关闭加密")
        state = str(user["encryption_state"] or "encrypted")
        if state in ACTIVE_STATES:
            raise Conflict("加密任务正在进行中，请稍后再试", code="conflict")
        if enabled and state == "encrypted" and bool(user["encryption_enabled"]):
            return self.status(user_id)
        if not enabled and state == "plaintext":
            return self.status(user_id)
        direction = "encrypt" if enabled else "decrypt"
        job_id = random_id("j", 8)
        now = self.clock.now()
        self.db.execute(
            "INSERT INTO crypto_jobs(id, user_id, direction, status, total, done, "
            "cursor, error, created_at) VALUES (?,?,?,'queued',0,0,'','',?)",
            (job_id, user_id, direction, now),
        )
        self.db.execute(
            "UPDATE users SET encryption_state = ? WHERE id = ?",
            ("encrypting" if enabled else "decrypting", user_id),
        )
        self.audit.log(
            actor_id=actor_id,
            actor_role=actor_role,
            action="user.encryption_requested",
            target_type="user",
            target_id=user_id,
            ip=ip,
            reason=reason,
            detail={"enabled": enabled, "job_id": job_id},
        )
        task = asyncio.create_task(
            self._run(
                job_id=job_id,
                user_id=user_id,
                decrypt=not enabled,
                actor_id=actor_id,
                actor_role=actor_role,
                ip=ip,
            )
        )
        self._tasks[job_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(job_id, None))
        return self.status(user_id)

    async def _run(
        self,
        *,
        job_id: str,
        user_id: str,
        decrypt: bool,
        actor_id: str,
        actor_role: str,
        ip: str,
    ) -> None:
        now = self.clock.now()
        self.db.execute(
            "UPDATE crypto_jobs SET status = 'running', started_at = ? WHERE id = ?",
            (now, job_id),
        )
        bots = self.db.query(
            "SELECT id, memory_db FROM bots WHERE user_id = ? AND status != 'deleted'",
            (user_id,),
        )
        total = max(1, len(bots) * 3)
        self.db.execute(
            "UPDATE crypto_jobs SET total = ? WHERE id = ?", (total, job_id)
        )
        done = 0
        errors: list[str] = []
        for bot in bots:
            bot_id = str(bot["id"])
            # 1) memory library
            try:
                self._convert_memory(bot_id, user_id, decrypt)
            except Exception as exc:  # noqa: BLE001
                logger.exception("记忆库转换失败：%s", bot_id)
                errors.append(f"记忆库 {bot_id}: {exc}")
            done += 1
            self._progress(job_id, done, f"memory:{bot_id}")
            # 2) credentials
            try:
                self.container.bots.convert_credentials(bot_id, decrypt=decrypt)
            except Exception as exc:  # noqa: BLE001
                logger.exception("凭据转换失败：%s", bot_id)
                errors.append(f"凭据 {bot_id}: {exc}")
            done += 1
            self._progress(job_id, done, f"credential:{bot_id}")
            # 3) conversations
            try:
                await self.container.conversations.backfill_bot(bot_id, decrypt=decrypt)
            except Exception as exc:  # noqa: BLE001
                logger.exception("对话转换失败：%s", bot_id)
                errors.append(f"对话 {bot_id}: {exc}")
            done += 1
            self._progress(job_id, done, f"conversation:{bot_id}")
            await asyncio.sleep(0.05)  # rate limit between bots

        finished = self.clock.now()
        if errors:
            self.db.execute(
                "UPDATE crypto_jobs SET status = 'paused', error = ?, finished_at = ? WHERE id = ?",
                ("\n".join(errors)[:2000], finished, job_id),
            )
            self.db.execute(
                "UPDATE users SET encryption_state = 'paused' WHERE id = ?", (user_id,)
            )
            self.audit.log(
                actor_id=actor_id,
                actor_role=actor_role,
                action="user.encryption_paused",
                target_type="user",
                target_id=user_id,
                ip=ip,
                detail={"job_id": job_id, "errors": errors[:5]},
            )
            return
        self.db.execute(
            "UPDATE crypto_jobs SET status = 'done', done = total, cursor = '', "
            "finished_at = ? WHERE id = ?",
            (finished, job_id),
        )
        self.db.execute(
            "UPDATE users SET encryption_enabled = ?, encryption_state = ?, "
            "encryption_changed_at = ?, encryption_changed_by = ? WHERE id = ?",
            (
                0 if decrypt else 1,
                "plaintext" if decrypt else "encrypted",
                finished,
                actor_id,
                user_id,
            ),
        )
        self.audit.log(
            actor_id=actor_id,
            actor_role=actor_role,
            action="user.encryption_changed",
            target_type="user",
            target_id=user_id,
            ip=ip,
            detail={"enabled": not decrypt, "job_id": job_id, "bots": len(bots)},
        )

    def _progress(self, job_id: str, done: int, cursor: str) -> None:
        self.db.execute(
            "UPDATE crypto_jobs SET done = ?, cursor = ? WHERE id = ?",
            (done, cursor, job_id),
        )

    def _convert_memory(self, bot_id: str, user_id: str, decrypt: bool) -> None:
        storage = self.container.memory_storage
        if not storage.exists(bot_id):
            return
        key = self.container.tenants.memory_key(user_id, bot_id)
        self.container.memory_store.close(bot_id)
        if decrypt:
            storage.to_plaintext(bot_id, key)
        else:
            storage.to_encrypted(bot_id, key)

    # -- test / admin helpers -----------------------------------------
    async def wait_idle(self, user_id: str, timeout: float = 20.0) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            status = self.status(user_id)
            if status["state"] not in ACTIVE_STATES:
                return status
            await asyncio.sleep(0.05)
        return self.status(user_id)
