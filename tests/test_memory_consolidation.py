"""Rule-based sleep consolidation: merge, decay, forget + reports.

Target 3: ``consolidate_bot(bot_id, dry_run=False) -> report``.
"""

from __future__ import annotations

import pytest

from saas.clock import FrozenClock
from saas.memory.consolidation import (
    ConsolidationConfig,
    MemoryConsolidator,
    consolidate_bot,
    similarity,
)
from saas.memory.models import MemoryDraft
from saas.memory.storage.in_memory import InMemoryRepository
from saas.memory.storage.repository import SqlCipherRepository
from saas.memory.storage.sqlcipher import MemoryStorage
from saas.memory.store import InMemoryStore

KEY = b"k" * 32
START = 1_700_000_000
DAY = 86400


class _Store:
    """Minimal store wrapper so both backends expose ``open(bot_id)``."""

    def __init__(self, repository) -> None:
        self.repository = repository

    def open(self, bot_id: str):  # noqa: ARG002 - single-bot test double
        return self.repository


def _seed(
    store,
    content: str,
    *,
    created_at: int,
    strength: int = 50,
    importance: int = 3,
    pinned: bool = False,
    tags: list[str] | None = None,
    last_recalled_at: int = 0,
):
    repository = store.open("b1")
    memory_id = repository.add(
        MemoryDraft(
            content=content,
            kind="knowledge",
            importance=importance,
            pinned=pinned,
            strength=strength,
            tags=tags or [],
        ),
        now=created_at,
    )
    if last_recalled_at:
        repository.touch_recalled([memory_id], now=last_recalled_at)
    return memory_id


@pytest.fixture(params=["in_memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "in_memory":
        repository = InMemoryRepository()
    else:
        storage = MemoryStorage(tmp_path / "memory", force_plaintext=True)
        storage.create_library("b1", key=KEY, tenant_id="u1")
        repository = SqlCipherRepository(storage.open_library("b1", key=KEY))
    return _Store(repository)


@pytest.fixture
def clock():
    return FrozenClock(START)


# ---------------------------------------------------------------------------
# similarity helper
# ---------------------------------------------------------------------------
def test_similarity_normalizes_whitespace_and_punctuation():
    assert similarity("用户喜欢咖啡", "用户喜欢 咖啡！") == 1.0
    assert similarity("用户喜欢咖啡", "用户喜欢喝茶") < 0.8
    assert similarity("", "任意内容") == 0.0


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------
def test_merge_similar_memories_within_24h(store, clock):
    first = _seed(
        store,
        "用户喜欢喝咖啡",
        created_at=START,
        strength=40,
        importance=3,
        tags=["饮食"],
    )
    second = _seed(
        store,
        "用户喜欢喝咖啡。",
        created_at=START + 3600,
        strength=80,
        importance=5,
        tags=["偏好"],
    )
    unrelated = _seed(store, "用户养了一只猫", created_at=START + 7200)

    report = MemoryConsolidator(store, clock=clock).consolidate_bot("b1")

    assert report["scanned"] == 3
    assert report["merged_records"] == 1
    assert len(report["merged_groups"]) == 1
    group = report["merged_groups"][0]
    assert group["representative"] == second  # highest strength/importance survives
    assert group["source_ids"] == [first]
    assert group["strength"] == 85  # 80 + 5 bonus
    assert group["tags"] == ["偏好", "饮食"]

    repository = store.open("b1")
    survivor = repository.get(second)
    assert survivor is not None
    assert survivor.tags == ["偏好", "饮食"]
    assert survivor.strength == 85
    assert survivor.importance == 5
    assert survivor.metadata["merged_from"] == [first]
    assert survivor.metadata["consolidated_at"] == START

    merged_away = store.open("b1")
    assert merged_away.get(first) is None
    assert merged_away.get(unrelated) is not None
    # Raw rows keep the pointer for auditing (soft delete, not hard delete).
    raw = getattr(repository, "_items", None)
    if raw is not None:
        assert raw[first].metadata["merged_into"] == second
        assert raw[first].deleted_at == START
    else:
        row = repository.conn.execute(
            "SELECT metadata, deleted_at FROM memories WHERE id = ?", (first,)
        ).fetchone()
        assert row["deleted_at"] == START
        assert f'"merged_into": {second}' in row["metadata"]


def test_no_merge_outside_window(store, clock):
    _seed(store, "用户喜欢喝咖啡", created_at=START)
    _seed(store, "用户喜欢喝咖啡。", created_at=START + 2 * DAY)
    report = MemoryConsolidator(store, clock=clock).consolidate_bot("b1")
    assert report["merged_records"] == 0
    assert report["merged_groups"] == []
    assert store.open("b1").count() == 2


def test_pinned_memory_survives_as_representative(store, clock):
    pinned = _seed(
        store,
        "用户喜欢喝咖啡",
        created_at=START,
        strength=10,
        importance=2,
        pinned=True,
    )
    normal = _seed(
        store,
        "用户喜欢喝咖啡。",
        created_at=START + 60,
        strength=90,
        importance=4,
    )
    report = MemoryConsolidator(store, clock=clock).consolidate_bot("b1")
    assert report["merged_groups"][0]["representative"] == pinned
    assert report["merged_groups"][0]["source_ids"] == [normal]
    assert store.open("b1").get(pinned) is not None
    assert store.open("b1").get(normal) is None


# ---------------------------------------------------------------------------
# decay / forget
# ---------------------------------------------------------------------------
def test_decay_uses_half_life(store, clock):
    memory_id = _seed(
        store,
        "很久没被想起的旧记忆",
        created_at=START - 28 * DAY,
        strength=80,
        importance=3,
    )
    clock.set(START)
    report = MemoryConsolidator(store, clock=clock).consolidate_bot("b1")

    assert len(report["decayed"]) == 1
    decay = report["decayed"][0]
    assert decay["memory_id"] == memory_id
    assert decay["before"] == 80
    assert decay["after"] == 20  # 80 * 0.5^(28/14) = 20
    memory = store.open("b1").get(memory_id)
    assert memory.strength == 20
    assert memory.last_decay_at == START
    assert report["forgotten"] == []

    # Same clock: no time elapsed since the last decay → idempotent no-op.
    again = MemoryConsolidator(store, clock=clock).consolidate_bot("b1")
    assert again["decayed"] == []


def test_recent_recall_prevents_decay(store, clock):
    _seed(
        store,
        "最近刚被召回",
        created_at=START - 30 * DAY,
        strength=60,
        last_recalled_at=START - 2 * DAY,
    )
    clock.set(START)
    report = MemoryConsolidator(store, clock=clock).consolidate_bot("b1")
    assert report["decayed"] == []
    assert store.open("b1").list()[0].strength == 60


def test_decay_skips_pinned(store, clock):
    memory_id = _seed(
        store,
        "置顶记忆永不衰减",
        created_at=START - 100 * DAY,
        strength=5,
        importance=1,
        pinned=True,
    )
    report = MemoryConsolidator(store, clock=clock).consolidate_bot("b1")
    assert report["decayed"] == []
    assert report["forgotten"] == []
    assert store.open("b1").get(memory_id).strength == 5


def test_forget_below_threshold_and_low_importance(store, clock):
    weak = _seed(
        store,
        "低重要度的旧寒暄",
        created_at=START - 40 * DAY,
        strength=6,
        importance=2,
    )
    important = _seed(
        store,
        "低强度但重要的约定",
        created_at=START - 40 * DAY,
        strength=6,
        importance=4,
    )
    clock.set(START)
    report = MemoryConsolidator(store, clock=clock).consolidate_bot("b1")

    assert weak in report["forgotten"]
    assert important not in report["forgotten"]
    repository = store.open("b1")
    assert repository.get(weak) is None
    survivor = repository.get(important)
    assert survivor is not None
    assert survivor.strength < 6  # decayed, but kept because importance > 2


def test_dry_run_reports_without_writing(store, clock):
    first = _seed(store, "用户喜欢喝咖啡", created_at=START, strength=40)
    second = _seed(store, "用户喜欢喝咖啡。", created_at=START + 60, strength=60)
    stale = _seed(
        store,
        "陈年旧事",
        created_at=START - 30 * DAY,
        strength=8,
        importance=1,
    )
    clock.set(START)
    report = MemoryConsolidator(store, clock=clock).consolidate_bot("b1", dry_run=True)

    assert report["dry_run"] is True
    assert report["merged_records"] == 1
    assert [item["memory_id"] for item in report["decayed"]] == [stale]
    assert stale in report["forgotten"]
    repository = store.open("b1")
    assert repository.get(first).strength == 40
    assert repository.get(second).strength == 60
    assert repository.get(stale).strength == 8
    assert repository.count() == 3
    raw = getattr(repository, "_items", None)
    if raw is not None:
        assert "merged_into" not in raw[first].metadata
        assert raw[first].deleted_at == 0


def test_report_shape_and_module_function(store, clock):
    _seed(store, "普通记忆", created_at=START)
    report = consolidate_bot(store, "b1", clock=clock)
    assert set(report) >= {
        "bot_id",
        "dry_run",
        "now",
        "scanned",
        "merged_groups",
        "merged_records",
        "decayed",
        "forgotten",
        "kept",
    }
    assert report["bot_id"] == "b1"
    assert report["now"] == START
    assert report["kept"] == 1
    assert report["merged_records"] == 0
    assert report["decayed"] == []


def test_custom_config_threshold(store, clock):
    _seed(store, "用户喜欢喝咖啡", created_at=START, strength=40)
    _seed(store, "用户喜欢喝咖啡。", created_at=START + 60, strength=60)
    config = ConsolidationConfig(merge_window_seconds=30)
    report = MemoryConsolidator(store, clock=clock, config=config).consolidate_bot("b1")
    assert report["merged_records"] == 0  # 60s apart > 30s window


def test_consolidation_persists_across_sqlcipher_reopen(tmp_path, clock):
    storage = MemoryStorage(tmp_path / "memory", force_plaintext=True)
    storage.create_library("b1", key=KEY, tenant_id="u1")
    repository = SqlCipherRepository(storage.open_library("b1", key=KEY))
    store = _Store(repository)
    survivor = _seed(store, "用户喜欢喝咖啡", created_at=START, strength=70)
    absorbed = _seed(store, "用户喜欢喝咖啡。", created_at=START + 60, strength=30)
    clock.set(START)
    report = MemoryConsolidator(store, clock=clock).consolidate_bot("b1")
    assert report["merged_records"] == 1
    repository.conn.close()

    reopened = SqlCipherRepository(storage.open_library("b1", key=KEY))
    assert reopened.get(survivor).strength == 75  # 70 + 5
    assert reopened.get(survivor).metadata["merged_from"] == [absorbed]
    assert reopened.get(absorbed) is None
