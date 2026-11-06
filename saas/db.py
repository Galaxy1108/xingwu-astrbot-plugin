"""SQLite access layer for plugin data (WAL, migrations, short transactions).

Only this module opens the plugin database; services receive a :class:`Database`
and must not hold raw connections (same rule as the memory module).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Database:
    """Thread-safe SQLite wrapper with explicit transactions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._depth = 0
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle -----------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is not None:
                return self._conn
            conn = sqlite3.connect(
                self.path, check_same_thread=False, isolation_level=None, timeout=10
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            self._conn = conn
            return conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connect()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # -- statements ----------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, tuple(params))

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        with self._lock:
            self.conn.executemany(sql, rows)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(sql, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row is not None else None

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if not row:
            return default
        return next(iter(row.values()), default)

    def commit(self) -> None:
        with self._lock:
            self.conn.commit()

    def rollback(self) -> None:
        with self._lock:
            if self._depth > 0:
                return
            self.conn.rollback()

    # -- transactions --------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Explicit ``BEGIN IMMEDIATE`` transaction, nestable via savepoints."""
        with self._lock:
            conn = self.conn
            if self._depth == 0:
                conn.execute("BEGIN IMMEDIATE")
            else:
                conn.execute(f"SAVEPOINT sp_{self._depth}")
            self._depth += 1
            try:
                yield conn
            except BaseException:
                self._depth -= 1
                if self._depth == 0:
                    conn.execute("ROLLBACK")
                else:
                    conn.execute(f"ROLLBACK TO sp_{self._depth}")
                    conn.execute(f"RELEASE sp_{self._depth}")
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    conn.execute("COMMIT")
                else:
                    conn.execute(f"RELEASE sp_{self._depth}")

    # -- migrations ----------------------------------------------------
    def run_migrations(self, migrations_dir: str | Path | None = None) -> list[int]:
        """Apply pending ``NNN_*.sql`` migrations in order; idempotent."""
        directory = Path(migrations_dir) if migrations_dir else None
        if directory is None:
            directory = Path(__file__).resolve().parent / "migrations"
        with self._lock:
            conn = self.conn
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
            )
            applied = {
                row[0]
                for row in conn.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            pending: list[tuple[int, Path]] = []
            for path in sorted(directory.glob("*.sql")):
                try:
                    version = int(path.name.split("_", 1)[0])
                except ValueError:
                    logger.warning("Skipping migration without numeric prefix: %s", path)
                    continue
                if version not in applied:
                    pending.append((version, path))
            now = int(__import__("time").time())
            done: list[int] = []
            for version, path in sorted(pending):
                sql = path.read_text(encoding="utf-8")
                script = (
                    "BEGIN IMMEDIATE;\n"
                    f"{sql}\n"
                    f"INSERT INTO schema_migrations(version, applied_at) "
                    f"VALUES ({version}, {now});\n"
                    "COMMIT;"
                )
                try:
                    conn.executescript(script)
                except Exception:
                    logger.exception("Migration %s failed", path.name)
                    try:
                        conn.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    raise
                done.append(version)
                logger.info("Applied migration %s", path.name)
            return done
