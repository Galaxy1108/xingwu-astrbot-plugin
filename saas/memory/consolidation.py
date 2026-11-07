"""Rule-based "sleep consolidation" for the self-hosted memory module.

Angel memory runs a nightly hygiene pass (``consolidate_memories``): it merges
highly similar memories, accumulates strengths and lets stale memories decay.
This module is the self-hosted rule-based equivalent — no LLM required:

* **merge**: within a sliding 24h window, memories whose normalized content is
  highly similar are collapsed into the strongest / most important one. Tags
  are unioned, strengths accumulate, and the absorbed rows are soft-deleted
  with ``metadata.merged_into`` pointing at the survivor.
* **decay**: memories not recalled for ``decay_idle_days`` lose strength with a
  half-life of ``half_life_days`` (exponential; each run accounts for the time
  elapsed since the previous decay/recall).
* **forget**: decayed memories below ``forget_strength_threshold`` with
  ``importance <= forget_max_importance`` are soft-deleted.

The entry point is ``consolidate_bot(bot_id, dry_run=False) -> report``
(available as a module function and as ``MemoryConsolidator.consolidate_bot``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from ..clock import Clock, SystemClock
from .models import Memory, MAX_STRENGTH, normalize_content

logger = logging.getLogger(__name__)

DAY = 86400


@dataclass(frozen=True)
class ConsolidationConfig:
    merge_window_seconds: int = DAY
    similarity_threshold: float = 0.8
    merge_strength_bonus: int = 5
    max_merge_group: int = 8
    decay_idle_days: float = 7.0
    half_life_days: float = 14.0
    forget_strength_threshold: int = 10
    forget_max_importance: int = 2
    protect_pinned: bool = True


def similarity(left: str, right: str) -> float:
    """Similarity of two memories on their normalized content (0..1)."""
    a = normalize_content(left)
    b = normalize_content(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _merge_groups(
    memories: list[Memory], config: ConsolidationConfig
) -> list[list[Memory]]:
    """Greedy sliding-window clustering of highly similar memories."""
    groups: list[list[Memory]] = []
    assigned: set[int] = set()
    ordered = sorted(memories, key=lambda memory: (memory.created_at, memory.id))
    for index, anchor in enumerate(ordered):
        if anchor.id in assigned:
            continue
        group = [anchor]
        assigned.add(anchor.id)
        for candidate in ordered[index + 1 :]:
            if candidate.id in assigned:
                continue
            if candidate.created_at - anchor.created_at > config.merge_window_seconds:
                break
            if len(group) >= config.max_merge_group:
                break
            if (
                similarity(anchor.content, candidate.content)
                >= config.similarity_threshold
            ):
                group.append(candidate)
                assigned.add(candidate.id)
        if len(group) > 1:
            groups.append(group)
    return groups


def _pick_representative(group: list[Memory]) -> Memory:
    """Keep the highest strength/importance (pinned wins) memory."""
    return max(
        group,
        key=lambda memory: (
            1 if memory.pinned else 0,
            memory.strength,
            memory.importance,
            memory.created_at,
            memory.id,
        ),
    )


class MemoryConsolidator:
    """Orchestrates merge/decay/forget for one bot library at a time."""

    def __init__(
        self,
        store: Any,
        *,
        clock: Clock | None = None,
        config: ConsolidationConfig | None = None,
        events: Any | None = None,
    ) -> None:
        # Accept either a store or a MemoryService (it exposes ``.store``).
        self.store = getattr(store, "store", store)
        self.clock = clock or SystemClock()
        self.config = config or ConsolidationConfig()
        self.events = events

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.events is None:
            return
        try:
            self.events.publish(event, payload)
        except Exception:  # noqa: BLE001
            logger.warning("consolidation event publish failed: %s", event, exc_info=True)

    # -- entry point ---------------------------------------------------
    def consolidate_bot(self, bot_id: str, *, dry_run: bool = False) -> dict[str, Any]:
        repository = self.store.open(bot_id)
        now = int(self.clock.now())
        config = self.config
        report: dict[str, Any] = {
            "bot_id": bot_id,
            "dry_run": bool(dry_run),
            "now": now,
            "scanned": 0,
            "merged_groups": [],
            "merged_records": 0,
            "decayed": [],
            "forgotten": [],
            "kept": 0,
        }

        memories = [
            memory for memory in repository.list(limit=100_000) if not memory.deleted_at
        ]
        report["scanned"] = len(memories)

        merged_ids: set[int] = set()
        for group in _merge_groups(memories, config):
            representative = _pick_representative(group)
            sources = [memory for memory in group if memory.id != representative.id]
            tags = sorted(
                {tag for memory in group for tag in memory.tags if tag}
            )
            merged_strength = min(
                MAX_STRENGTH,
                max(memory.strength for memory in group)
                + config.merge_strength_bonus * len(sources),
            )
            entry = {
                "representative": representative.id,
                "source_ids": [memory.id for memory in sources],
                "strength": merged_strength,
                "importance": max(memory.importance for memory in group),
                "tags": tags,
            }
            report["merged_groups"].append(entry)
            report["merged_records"] += len(sources)
            merged_ids.add(representative.id)
            merged_ids.update(memory.id for memory in sources)
            if dry_run:
                continue
            representative.tags = tags
            representative.importance = entry["importance"]
            representative.strength = merged_strength
            representative.metadata = dict(representative.metadata or {})
            representative.metadata["merged_from"] = [
                *representative.metadata.get("merged_from", []),
                *entry["source_ids"],
            ]
            representative.metadata["consolidated_at"] = now
            repository.update(representative, now=now)
            for memory in sources:
                metadata = dict(memory.metadata or {})
                metadata["merged_into"] = representative.id
                metadata["merged_at"] = now
                memory.metadata = metadata
                repository.update(memory, now=now)
                repository.soft_delete(memory.id, now=now)

        # Re-read so soft-deleted merge sources do not take part in decay.
        active = [
            memory for memory in repository.list(limit=100_000) if not memory.deleted_at
        ]
        decays: list[tuple[int, int]] = []
        forgotten_ids: list[int] = []
        half_life_seconds = max(1.0, float(config.half_life_days) * DAY)
        idle_seconds = max(0.0, float(config.decay_idle_days) * DAY)
        for memory in active:
            if memory.id in merged_ids:
                # Freshly consolidated memories get one clean cycle before decay.
                continue
            if config.protect_pinned and memory.pinned:
                continue
            last_seen = max(
                memory.last_recalled_at or 0,
                memory.created_at or 0,
            )
            if now - last_seen < idle_seconds:
                continue
            baseline = max(
                memory.last_recalled_at or 0,
                memory.last_decay_at or 0,
                memory.created_at or 0,
            )
            elapsed = now - baseline
            if elapsed <= 0:
                continue
            factor = 0.5 ** (elapsed / half_life_seconds)
            if factor >= 0.999:
                continue
            new_strength = int(round(memory.strength * factor))
            if new_strength >= memory.strength:
                continue
            report["decayed"].append(
                {
                    "memory_id": memory.id,
                    "before": memory.strength,
                    "after": new_strength,
                }
            )
            decays.append((memory.id, new_strength))
            if (
                new_strength < config.forget_strength_threshold
                and memory.importance <= config.forget_max_importance
            ):
                forgotten_ids.append(memory.id)
                report["forgotten"].append(memory.id)

        report["kept"] = max(0, len(active) - len(forgotten_ids))
        if not dry_run:
            if decays:
                repository.apply_decay(decays, now=now)
            for memory_id in forgotten_ids:
                memory = repository.get(memory_id)
                if memory is None:
                    continue
                metadata = dict(memory.metadata or {})
                metadata["forgotten_by"] = "decay"
                metadata["forgotten_at"] = now
                memory.metadata = metadata
                repository.update(memory, now=now)
                repository.soft_delete(memory_id, now=now)
            if report["merged_groups"] or decays:
                self._emit(
                    "memory.consolidated",
                    {
                        "bot_id": bot_id,
                        "merged_records": report["merged_records"],
                        "decayed": len(report["decayed"]),
                        "forgotten": len(report["forgotten"]),
                    },
                )
        return report


def consolidate_bot(
    store: Any,
    bot_id: str,
    *,
    dry_run: bool = False,
    clock: Clock | None = None,
    config: ConsolidationConfig | None = None,
    events: Any | None = None,
) -> dict[str, Any]:
    """Module-level convenience wrapper around :class:`MemoryConsolidator`."""
    consolidator = MemoryConsolidator(
        store, clock=clock, config=config, events=events
    )
    return consolidator.consolidate_bot(bot_id, dry_run=dry_run)


__all__ = [
    "ConsolidationConfig",
    "MemoryConsolidator",
    "consolidate_bot",
    "similarity",
]
