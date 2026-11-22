"""Error-log retention: clear() drops old rows, and the daily gate throttles it."""

from __future__ import annotations

from saas.container import Container
from saas.observe import (
    ERROR_LOG_CLEAN_INTERVAL_SECONDS,
    ERROR_LOG_RETENTION_DAYS,
    IntervalGate,
)


def test_clear_removes_only_entries_older_than_retention(
    container: Container, clock
):
    now = clock.now()
    old_at = now - (ERROR_LOG_RETENTION_DAYS + 1) * 86400
    recent_at = now - 3600
    container.db.execute(
        "INSERT INTO error_logs(level, message, created_at) VALUES ('error', 'old', ?)",
        (old_at,),
    )
    container.db.execute(
        "INSERT INTO error_logs(level, message, created_at) VALUES ('error', 'new', ?)",
        (recent_at,),
    )

    removed = container.error_logs.clear(older_than_days=ERROR_LOG_RETENTION_DAYS)

    assert removed == 1
    remaining = container.db.query("SELECT message FROM error_logs")
    assert [row["message"] for row in remaining] == ["new"]


def test_interval_gate_runs_at_most_once_per_interval():
    now = [1000.0]
    gate = IntervalGate(ERROR_LOG_CLEAN_INTERVAL_SECONDS, clock=lambda: now[0])

    assert gate.due() is True  # first call is always due
    now[0] += 60
    assert gate.due() is False  # the 60s gc tick does not re-run it
    now[0] += ERROR_LOG_CLEAN_INTERVAL_SECONDS
    assert gate.due() is True
