"""Runtime observability: API error records + in-memory backend log buffer."""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from .clock import Clock, SystemClock
from .db import Database

_SECRET_PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key|authorization|secret|password)\s*[:=]\s*\S+"), r"\1=***"),
    (re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"), "Bearer ***"),
    (re.compile(r"root_kek[^\s,]*"), "root_kek=***"),
]


def redact(text: str, *, limit: int = 4000) -> str:
    value = str(text or "")
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value[:limit]


class ErrorLogService:
    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self.db = db
        self.clock = clock or SystemClock()

    def record(
        self,
        *,
        level: str,
        message: str,
        source: str = "api",
        path: str = "",
        method: str = "",
        status: int = 500,
        code: str = "",
        detail: str = "",
        user_id: str = "",
        ip: str = "",
    ) -> int:
        cursor = self.db.execute(
            "INSERT INTO error_logs(level, source, path, method, status, code, message, "
            "detail, user_id, ip, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(level or "error")[:20],
                str(source or "api")[:40],
                str(path or "")[:300],
                str(method or "")[:10],
                int(status or 500),
                str(code or "")[:80],
                redact(message, limit=2000),
                redact(detail, limit=12000),
                str(user_id or "")[:80],
                str(ip or "")[:80],
                self.clock.now(),
            ),
        )
        return int(getattr(cursor, "lastrowid", 0) or 0)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        level: str | None = None,
        q: str | None = None,
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        where: list[str] = []
        params: list[Any] = []
        if level:
            where.append("level = ?")
            params.append(level)
        if q and q.strip():
            where.append("(message LIKE ? OR path LIKE ? OR code LIKE ?)")
            needle = f"%{q.strip()}%"
            params.extend([needle, needle, needle])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = int(
            self.db.scalar(f"SELECT COUNT(*) AS c FROM error_logs {clause}", params, 0)
        )
        items = self.db.query(
            f"SELECT * FROM error_logs {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def clear(self, *, older_than_days: int = 30) -> int:
        cutoff = self.clock.now() - max(1, int(older_than_days)) * 86400
        cursor = self.db.execute(
            "DELETE FROM error_logs WHERE created_at < ?", (cutoff,)
        )
        return int(getattr(cursor, "rowcount", 0) or 0)


class AppLogBuffer(logging.Handler):
    """Keep the most recent backend log lines and mirror them to a file."""

    def __init__(self, *, capacity: int = 2000, log_file: Path | None = None) -> None:
        super().__init__(level=logging.INFO)
        self._records: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._file = log_file
        if log_file is not None:
            try:
                log_file.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                self._file = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            item = {
                "time": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": redact(message, limit=2000),
            }
            with self._lock:
                self._records.append(item)
                if self._file is not None:
                    if self._file.exists() and self._file.stat().st_size > 5 * 1024 * 1024:
                        try:
                            self._file.rename(self._file.with_suffix(".1.log"))
                        except OSError:
                            pass
                    with self._file.open("a", encoding="utf-8") as handle:
                        handle.write(
                            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(record.created))} "
                            f"[{record.levelname}] {record.name}: {item['message']}\n"
                        )
        except Exception:  # noqa: BLE001
            pass

    def tail(self, *, lines: int = 200, level: str = "") -> list[dict[str, Any]]:
        count = max(1, min(1000, int(lines or 200)))
        with self._lock:
            items = list(self._records)
        if level:
            items = [item for item in items if item["level"] == level]
        return items[-count:]


_LOG_HANDLER: AppLogBuffer | None = None


def install_log_capture(data_dir: Path) -> AppLogBuffer:
    global _LOG_HANDLER
    if _LOG_HANDLER is not None:
        return _LOG_HANDLER
    handler = AppLogBuffer(log_file=Path(data_dir) / "logs" / "backend.log")
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    _LOG_HANDLER = handler
    return handler


def log_buffer() -> AppLogBuffer | None:
    return _LOG_HANDLER


__all__ = [
    "AppLogBuffer",
    "ErrorLogService",
    "install_log_capture",
    "log_buffer",
    "redact",
]
