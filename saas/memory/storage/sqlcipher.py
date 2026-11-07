"""Per-Bot memory library bootstrap (SQLCipher).

M1 only needs *create/delete* (bot lifecycle step 4 + rollback). The full
memory module (repository/retrieval/tools) lands in M2 on top of this file.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path


logger = logging.getLogger(__name__)

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"


def dict_row_factory(cursor, row):
    """Row factory that works for both sqlite3 and sqlcipher3 cursors."""
    return {
        description[0]: row[index]
        for index, description in enumerate(cursor.description or ())
    }


class MemoryStorageError(RuntimeError):
    """Raised when a memory library cannot be created/opened."""


def sqlcipher_available() -> bool:
    try:
        import sqlcipher3  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _schema_files() -> list[tuple[int, Path]]:
    files: list[tuple[int, Path]] = []
    for path in sorted(SCHEMA_DIR.glob("*.sql")):
        try:
            files.append((int(path.name.split("_", 1)[0]), path))
        except ValueError:
            continue
    return files


def _apply_schema(conn: sqlite3.Connection) -> None:
    """Apply pending per-bot schema files, recording versions in schema_migrations."""
    legacy = (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'memories'"
        ).fetchone()
        is not None
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
    )
    applied = {
        int(row[0])
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    if legacy and not applied:
        # Databases created before version tracking: only 003+ are pending; the
        # 003 migration upgrades the old FTS layout in place.
        applied = {1, 2}
        now = int(__import__("time").time())
        conn.executemany(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            [(1, now), (2, now)],
        )
    now = int(__import__("time").time())
    for version, path in _schema_files():
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, now),
        )
        applied.add(version)
    conn.commit()


PRAGMAS = (
    "PRAGMA cipher_page_size = 4096;",
    "PRAGMA kdf_iter = 256000;",
    "PRAGMA cipher_hmac_algorithm = HMAC_SHA512;",
    "PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;",
    "PRAGMA journal_mode = WAL;",
    "PRAGMA temp_store = MEMORY;",
    "PRAGMA synchronous = NORMAL;",
)


class MemoryStorage:
    """Creates/deletes the encrypted per-bot SQLite files.

    ``key_provider(bot_id)`` returns the 32-byte SQLCipher key derived from the
    tenant key (``HKDF(tenant_key, salt=bot_id, info="bot/memory/v1")``).
    """

    def __init__(
        self,
        memory_dir: str | Path,
        *,
        force_plaintext: bool = False,
    ) -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.encrypted = sqlcipher_available() and not force_plaintext
        if not self.encrypted:
            logger.error(
                "SQLCipher 不可用：记忆库降级为普通 SQLite + 字段加密（请安装 sqlcipher3）"
            )

    # -- paths ---------------------------------------------------------
    def path_for(self, bot_id: str) -> Path:
        return self.memory_dir / f"{bot_id}.db"

    def relative_path(self, bot_id: str) -> str:
        return f"memory/{bot_id}.db"

    def exists(self, bot_id: str) -> bool:
        return self.path_for(bot_id).exists()

    # -- connections ---------------------------------------------------
    def _connect(self, bot_id: str, key: bytes | None = None) -> sqlite3.Connection:
        path = self.path_for(bot_id)
        if self.encrypted:
            import sqlcipher3

            conn = sqlcipher3.connect(str(path))
            if key is None:
                raise MemoryStorageError("加密记忆库必须提供 32 字节密钥")
            if len(key) != 32:
                raise MemoryStorageError("记忆库密钥长度必须为 32 字节")
            conn.execute(f'PRAGMA key = "x\'{key.hex()}\'";')
            for pragma in PRAGMAS:
                conn.execute(pragma)
        else:
            conn = sqlite3.connect(str(path))
            conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = dict_row_factory
        return conn

    # -- lifecycle -----------------------------------------------------
    def create_library(self, bot_id: str, *, key: bytes, tenant_id: str) -> str:
        """Create ``memory/<bot_id>.db`` with schema + meta; returns relative path."""
        path = self.path_for(bot_id)
        if path.exists():
            raise MemoryStorageError(f"记忆库已存在：{path.name}")
        now = int(__import__("time").time())
        conn = self._connect(bot_id, key)
        try:
            _apply_schema(conn)
            conn.executemany(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                [
                    ("bot_id", bot_id),
                    ("tenant_id", tenant_id),
                    ("created_at", str(now)),
                    ("backend", "sqlcipher" if self.encrypted else "plaintext"),
                    ("schema_version", "2"),
                ],
            )
            conn.commit()
            # Ensure the encrypted header is flushed before closing.
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as exc:  # noqa: BLE001
            conn.close()
            self._remove_files(path)
            raise MemoryStorageError(f"创建记忆库失败：{exc}") from exc
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        if self.encrypted:
            header = path.read_bytes()[:16]
            if header.startswith(b"SQLite format 3\x00"):
                self._remove_files(path)
                raise MemoryStorageError(
                    "记忆库未加密（SQLCipher PRAGMA key 未生效），已删除该文件"
                )
        return self.relative_path(bot_id)

    # -- plaintext <-> SQLCipher conversion (M3 encryption switch) ------
    def is_encrypted(self, bot_id: str) -> bool:
        path = self.path_for(bot_id)
        if not path.exists():
            return False
        return not path.read_bytes()[:16].startswith(b"SQLite format 3")

    def _replace(self, target: Path, source: Path) -> None:
        os.replace(source, target)
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                Path(str(target) + suffix).unlink()
            except FileNotFoundError:
                pass

    def to_plaintext(self, bot_id: str, key: bytes) -> bool:
        """SQLCipher -> plain SQLite via ``sqlcipher_export`` (in place).

        Returns True when a conversion happened, False when already plaintext.
        """
        path = self.path_for(bot_id)
        if not path.exists() or not self.encrypted or not self.is_encrypted(bot_id):
            return False
        tmp = path.with_suffix(".plain.tmp")
        if tmp.exists():
            tmp.unlink()
        import sqlcipher3

        conn = sqlcipher3.connect(str(path))
        try:
            conn.execute(f'PRAGMA key = "x\'{key.hex()}\'";')
            conn.execute(f"ATTACH DATABASE '{tmp}' AS plaintext KEY '';")
            conn.execute("SELECT sqlcipher_export('plaintext');")
            conn.execute("DETACH DATABASE plaintext;")
            conn.commit()
        finally:
            conn.close()
        self._replace(path, tmp)
        check = sqlite3.connect(str(path))
        try:
            check.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('backend', 'plaintext')"
            )
            check.commit()
        finally:
            check.close()
        return True

    def to_encrypted(self, bot_id: str, key: bytes) -> bool:
        """Plain SQLite -> SQLCipher via ``sqlcipher_export`` (in place)."""
        path = self.path_for(bot_id)
        if not path.exists():
            return False
        if not self.encrypted:
            raise MemoryStorageError("当前环境没有 SQLCipher，无法加密记忆库")
        if self.is_encrypted(bot_id):
            return False
        tmp = path.with_suffix(".enc.tmp")
        if tmp.exists():
            tmp.unlink()
        import sqlcipher3

        # Open the plaintext library through SQLCipher with an empty key, then
        # export into a keyed database.
        conn = sqlcipher3.connect(str(path))
        try:
            conn.execute(
                f"ATTACH DATABASE '{tmp}' AS encrypted KEY \"x'{key.hex()}'\";"
            )
            conn.execute("SELECT sqlcipher_export('encrypted');")
            conn.execute("DETACH DATABASE encrypted;")
            conn.commit()
        finally:
            conn.close()
        check = sqlcipher3.connect(str(tmp))
        try:
            check.execute(f'PRAGMA key = "x\'{key.hex()}\'";')
            check.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('backend', 'sqlcipher')"
            )
            check.commit()
        finally:
            check.close()
        if tmp.read_bytes()[:16].startswith(b"SQLite format 3"):
            tmp.unlink()
            raise MemoryStorageError("记忆库加密失败（导出文件仍为明文）")
        self._replace(path, tmp)
        return True

    def delete_library(self, bot_id: str) -> None:
        self._remove_files(self.path_for(bot_id))

    def _remove_files(self, path: Path) -> None:
        for candidate in (
            path,
            Path(str(path) + "-wal"),
            Path(str(path) + "-shm"),
            Path(str(path) + "-journal"),
        ):
            try:
                if candidate.exists():
                    os.unlink(candidate)
            except OSError:
                logger.warning("删除记忆库文件失败：%s", candidate, exc_info=True)

    # -- M2 placeholder -------------------------------------------------
    def open_library(self, bot_id: str, *, key: bytes | None = None) -> sqlite3.Connection:
        """Open an existing library; auto-detect plaintext vs SQLCipher."""
        path = self.path_for(bot_id)
        if not path.exists():
            raise MemoryStorageError(f"记忆库不存在：{path.name}")
        if not self.is_encrypted(bot_id):
            conn = sqlite3.connect(str(path))
            conn.row_factory = dict_row_factory
            return conn
        return self._connect(bot_id, key)

