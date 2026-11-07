"""Per-Bot vector index stored in the ``memory_vectors`` table.

Schema (``004_angel_parity.sql``)::

    memory_vectors(memory_id INTEGER PRIMARY KEY, model TEXT, dim INTEGER,
                   vector BLOB, updated_at INTEGER)

Vectors are ``float32`` packed with :func:`struct.pack`, so a BLOB is exactly
``4 * dim`` bytes and portable across numpy/no-numpy installations.  Cosine
similarity uses numpy when available and a pure-Python fallback otherwise.

The store only touches its own table plus a read-only join to ``memories`` for
``kind``/``since`` filtering; it never mutates memory rows.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import struct
import time
from dataclasses import dataclass
from typing import Any, Sequence

from .models import kind_variants

logger = logging.getLogger(__name__)

try:  # numpy is optional (requirements.txt does not pin it)
    import numpy as _np  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - exercised through monkeypatch in tests
    _np = None

FLOAT32_FORMAT = "f"
FLOAT32_SIZE = 4


class VectorStoreError(RuntimeError):
    """Raised when a vector cannot be encoded/decoded or stored."""


@dataclass(frozen=True)
class VectorRecord:
    memory_id: int
    model: str
    dim: int
    vector: list[float]
    updated_at: int


@dataclass(frozen=True)
class VectorHit:
    memory_id: int
    score: float


# --------------------------------------------------------------------------
# encoding / similarity
# --------------------------------------------------------------------------
def pack_vector(vector: Sequence[float]) -> bytes:
    """Pack a sequence of floats into a little-endian float32 BLOB."""
    values = [float(value) for value in vector]
    if not values:
        raise VectorStoreError("向量不能为空")
    if not all(math.isfinite(value) for value in values):
        raise VectorStoreError("向量包含 NaN/Inf")
    try:
        return struct.pack(f"<{len(values)}{FLOAT32_FORMAT}", *values)
    except (struct.error, OverflowError, TypeError, ValueError) as exc:
        raise VectorStoreError(f"向量编码失败：{exc}") from None


def unpack_vector(blob: Any, *, dim: int | None = None) -> list[float]:
    """Unpack a float32 BLOB, validating its byte length against ``dim``."""
    if blob is None:
        return []
    raw = bytes(blob)
    if not raw:
        return []
    if len(raw) % FLOAT32_SIZE:
        raise VectorStoreError("向量 BLOB 长度不是 4 的倍数")
    actual_dim = len(raw) // FLOAT32_SIZE
    if dim is not None and int(dim) != actual_dim:
        raise VectorStoreError(f"向量维度不匹配：期望 {dim}，实际 {actual_dim}")
    return list(struct.unpack(f"<{actual_dim}{FLOAT32_FORMAT}", raw))


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity; returns ``0.0`` for empty/mismatched/zero vectors."""
    if not left or not right or len(left) != len(right):
        return 0.0
    if _np is not None:
        try:
            a = _np.asarray(list(left), dtype="float32")
            b = _np.asarray(list(right), dtype="float32")
            norm = float(_np.linalg.norm(a) * _np.linalg.norm(b))
            if norm <= 0.0:
                return 0.0
            return float(_np.dot(a, b) / norm)
        except Exception:  # pragma: no cover - defensive fallback
            pass
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        a = float(a)
        b = float(b)
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------
def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


class MemoryVectorStore:
    """CRUD + cosine search over one Bot's ``memory_vectors`` table."""

    def __init__(self, repository: Any) -> None:
        conn = getattr(repository, "conn", None)
        if conn is None:
            raise VectorStoreError("当前记忆仓库不支持向量存储（缺少 SQL 连接）")
        self.repository = repository
        self.conn = conn

    # -- writes --------------------------------------------------------
    def upsert(
        self,
        memory_id: int,
        vector: Sequence[float],
        *,
        model: str = "",
        now: int | None = None,
    ) -> None:
        mid = int(memory_id)
        values = [float(value) for value in vector]
        blob = pack_vector(values)
        timestamp = int(now if now is not None else time.time())
        self.conn.execute(
            "INSERT OR REPLACE INTO memory_vectors"
            "(memory_id, model, dim, vector, updated_at) VALUES (?,?,?,?,?)",
            (mid, str(model or ""), len(values), sqlite3.Binary(blob), timestamp),
        )
        self.conn.commit()

    def delete(self, memory_id: int) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM memory_vectors WHERE memory_id = ?", (int(memory_id),)
        )
        self.conn.commit()
        return bool(cursor.rowcount)

    def delete_many(self, memory_ids: Sequence[int]) -> int:
        ids = [int(memory_id) for memory_id in memory_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        cursor = self.conn.execute(
            f"DELETE FROM memory_vectors WHERE memory_id IN ({placeholders})", ids
        )
        self.conn.commit()
        return int(cursor.rowcount or 0)

    # -- reads ---------------------------------------------------------
    def get(self, memory_id: int) -> VectorRecord | None:
        row = self.conn.execute(
            "SELECT memory_id, model, dim, vector, updated_at "
            "FROM memory_vectors WHERE memory_id = ?",
            (int(memory_id),),
        ).fetchone()
        if row is None:
            return None
        return self._record(row)

    def get_many(self, memory_ids: Sequence[int]) -> dict[int, VectorRecord]:
        ids = [int(memory_id) for memory_id in memory_ids]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            "SELECT memory_id, model, dim, vector, updated_at "
            f"FROM memory_vectors WHERE memory_id IN ({placeholders})",
            ids,
        ).fetchall()
        records: dict[int, VectorRecord] = {}
        for row in rows:
            try:
                record = self._record(row)
            except VectorStoreError:  # pragma: no cover - corrupt row
                logger.warning("跳过损坏的向量行", exc_info=True)
                continue
            records[record.memory_id] = record
        return records

    def count(self, *, model: str | None = None) -> int:
        if model:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM memory_vectors WHERE model = ?", (model,)
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM memory_vectors"
            ).fetchone()
        return int(_row_value(row, "c", 0) or 0) if row is not None else 0

    def search(
        self,
        query_vector: Sequence[float],
        limit: int = 50,
        *,
        kind: str | None = None,
        since: int | None = None,
        model: str | None = None,
    ) -> list[VectorHit]:
        """Return the most cosine-similar live memories for ``query_vector``.

        Rows whose ``dim`` differs from the query are ignored (they cannot be
        compared and usually belong to a previous embedding model).
        """
        query = [float(value) for value in query_vector]
        if not query:
            return []
        try:
            max_hits = max(1, int(limit))
        except (TypeError, ValueError):
            max_hits = 50

        where = ["m.deleted_at = 0", "v.dim = ?"]
        params: list[Any] = [len(query)]
        variants = kind_variants(kind)
        if variants:
            placeholders = ",".join("?" for _ in variants)
            where.append(f"m.kind IN ({placeholders})")
            params.extend(variants)
        if since:
            where.append("m.created_at >= ?")
            params.append(int(since))
        if model:
            where.append("v.model = ?")
            params.append(str(model))

        rows = self.conn.execute(
            "SELECT v.memory_id, v.model, v.dim, v.vector, v.updated_at "
            "FROM memory_vectors v JOIN memories m ON m.id = v.memory_id "
            f"WHERE {' AND '.join(where)}",
            params,
        ).fetchall()

        scored: list[VectorHit] = []
        for row in rows:
            try:
                vector = unpack_vector(
                    _row_value(row, "vector", 3), dim=int(_row_value(row, "dim", 2))
                )
            except (VectorStoreError, TypeError, ValueError):  # pragma: no cover
                logger.warning("跳过无法解码的向量行", exc_info=True)
                continue
            score = cosine_similarity(query, vector)
            scored.append(VectorHit(memory_id=int(_row_value(row, "memory_id", 0)), score=score))
        scored.sort(key=lambda hit: (-hit.score, -hit.memory_id))
        return scored[:max_hits]

    # -- helpers -------------------------------------------------------
    def _record(self, row: Any) -> VectorRecord:
        dim = int(_row_value(row, "dim", 2))
        return VectorRecord(
            memory_id=int(_row_value(row, "memory_id", 0)),
            model=str(_row_value(row, "model", 1) or ""),
            dim=dim,
            vector=unpack_vector(_row_value(row, "vector", 3), dim=dim),
            updated_at=int(_row_value(row, "updated_at", 4) or 0),
        )


__all__ = [
    "MemoryVectorStore",
    "VectorHit",
    "VectorRecord",
    "VectorStoreError",
    "cosine_similarity",
    "pack_vector",
    "unpack_vector",
]
