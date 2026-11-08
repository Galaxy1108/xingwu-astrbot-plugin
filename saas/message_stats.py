"""Per-user/bot daily message counters for the console dashboard."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .clock import Clock, SystemClock
from .db import Database


class MessageStatsService:
    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self.db = db
        self.clock = clock or SystemClock()

    def increment(
        self,
        *,
        user_id: str,
        bot_id: str,
        platform: str = "",
        at: int | None = None,
    ) -> None:
        if not user_id:
            return
        day = date.fromtimestamp(int(at or self.clock.now())).isoformat()
        self.db.execute(
            "INSERT INTO message_stats(user_id, bot_id, platform, day, count) "
            "VALUES (?,?,?,?,1) ON CONFLICT(user_id, bot_id, day) DO UPDATE "
            "SET count = count + 1, platform = excluded.platform",
            (user_id, bot_id, platform, day),
        )

    def series(self, user_id: str, *, days: int = 30) -> dict[str, Any]:
        days = max(1, min(90, int(days)))
        now = self.clock.now()
        end = date.fromtimestamp(now)
        start = end - timedelta(days=days - 1)
        rows = self.db.query(
            "SELECT day, platform, SUM(count) AS count FROM message_stats "
            "WHERE user_id = ? AND day >= ? GROUP BY day, platform",
            (user_id, start.isoformat()),
        )
        buckets: dict[str, dict[str, Any]] = {}
        for offset in range(days):
            key = (start + timedelta(days=offset)).isoformat()
            buckets[key] = {"date": key, "count": 0, "platforms": {}}
        by_platform: dict[str, int] = {}
        total = 0
        for row in rows:
            bucket = buckets.get(row["day"])
            if bucket is None:
                continue
            count = int(row["count"] or 0)
            bucket["count"] += count
            platform = row["platform"] or "unknown"
            bucket["platforms"][platform] = bucket["platforms"].get(platform, 0) + count
            by_platform[platform] = by_platform.get(platform, 0) + count
            total += count
        return {
            "days": days,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "total": total,
            "points": [buckets[key] for key in sorted(buckets)],
            "by_platform": [
                {"platform": key, "count": value}
                for key, value in sorted(by_platform.items(), key=lambda item: item[1], reverse=True)
            ],
        }


__all__ = ["MessageStatsService"]
