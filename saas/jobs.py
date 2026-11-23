"""Minimal in-process background job table.

Jobs live in memory only (single-process deployment) and are lost on restart.
A job is created synchronously, then its runner is scheduled as an asyncio
task. Runners report per-item progress through :meth:`JobStore.record_success`
and :meth:`JobStore.record_failure`; an item failure never aborts the job.

Status semantics:

* ``running`` – the runner has not returned yet.
* ``done``    – the runner returned normally (individual items may still have
  failed; see ``failed`` and ``errors``).
* ``failed``  – the runner itself raised, i.e. the job was interrupted.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MAX_JOBS = 200
RUNNING = "running"
DONE = "done"
FAILED = "failed"


@dataclass
class Job:
    id: str
    kind: str
    total: int
    status: str = RUNNING
    done: int = 0
    failed: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "kind": self.kind,
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "failed": self.failed,
            "errors": [dict(item) for item in self.errors],
        }


Runner = Callable[[Job], Awaitable[None]]


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()

    def create(self, kind: str, total: int) -> Job:
        job = Job(id=uuid.uuid4().hex, kind=kind, total=int(total))
        self._jobs[job.id] = job
        self._prune()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(str(job_id))

    def start(self, job: Job, runner: Runner) -> asyncio.Task:
        """Schedule ``runner(job)``; must be called from a running event loop."""
        task = asyncio.get_running_loop().create_task(self._run(job, runner))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _run(self, job: Job, runner: Runner) -> None:
        try:
            await runner(job)
        except Exception:  # noqa: BLE001 - reported through the job, not raised
            logger.exception("后台任务 %s (%s) 中断", job.id, job.kind)
            job.status = FAILED
            job.errors.append({"bot_id": "", "message": "后台任务中断"})
        else:
            job.status = DONE
        job.finished_at = time.time()

    @staticmethod
    def record_success(job: Job) -> None:
        job.done += 1

    @staticmethod
    def record_failure(job: Job, item_id: str, message: str) -> None:
        job.failed += 1
        job.errors.append({"bot_id": str(item_id), "message": message})

    def _prune(self) -> None:
        if len(self._jobs) <= MAX_JOBS:
            return
        finished = sorted(
            (j for j in self._jobs.values() if j.status != RUNNING),
            key=lambda j: j.created_at,
        )
        for job in finished[: len(self._jobs) - MAX_JOBS]:
            self._jobs.pop(job.id, None)


def jobs_of(container) -> JobStore:
    """Return the container-wide job store, created on first use."""
    store = getattr(container, "jobs", None)
    if store is None:
        store = JobStore()
        container.jobs = store
    return store
