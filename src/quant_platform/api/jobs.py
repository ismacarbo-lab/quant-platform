"""Tiny in-process job registry for long-running dashboard actions.

Fetching data, running backtests or replaying paper runs take seconds to
minutes, so the API starts them in a background thread and exposes their
status here. Local single-process use only; nothing is persisted.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from quant_platform.core.redact import redact_secret_text

JOB_STATUSES: tuple[str, ...] = ("queued", "running", "succeeded", "failed")


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def as_mapping(self, *, include_result: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": None
            if self.started_at is None
            else self.started_at.isoformat(),
            "finished_at": (
                None if self.finished_at is None else self.finished_at.isoformat()
            ),
            "error": self.error,
            "params": dict(self.params),
        }
        if include_result:
            payload["result"] = self.result
        return payload


class JobRegistry:
    def __init__(self, *, max_jobs: int = 200) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_jobs = max_jobs

    def submit(
        self,
        kind: str,
        runner: Callable[[], dict[str, Any]],
        *,
        params: dict[str, Any] | None = None,
    ) -> Job:
        job = Job(id=uuid4().hex, kind=kind, params=dict(params or {}))
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
        thread = threading.Thread(
            target=self._run, args=(job, runner), name=f"job-{kind}", daemon=True
        )
        thread.start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self, *, limit: int = 50) -> list[Job]:
        with self._lock:
            jobs = sorted(
                self._jobs.values(), key=lambda item: item.created_at, reverse=True
            )
        return jobs[:limit]

    def running(self, kind: str | None = None) -> list[Job]:
        with self._lock:
            return [
                job
                for job in self._jobs.values()
                if job.status in ("queued", "running")
                and (kind is None or job.kind == kind)
            ]

    def _run(self, job: Job, runner: Callable[[], dict[str, Any]]) -> None:
        job.status = "running"
        job.started_at = datetime.now(tz=UTC)
        try:
            job.result = runner()
            job.status = "succeeded"
        except Exception as exc:  # surfaced to the dashboard, never raised
            job.error = redact_secret_text(f"{type(exc).__name__}: {exc}")
            job.result = {
                "traceback": redact_secret_text(traceback.format_exc())[-4000:]
            }
            job.status = "failed"
        finally:
            job.finished_at = datetime.now(tz=UTC)

    def _trim(self) -> None:
        if len(self._jobs) <= self._max_jobs:
            return
        finished = sorted(
            (
                job
                for job in self._jobs.values()
                if job.status in ("succeeded", "failed")
            ),
            key=lambda item: item.created_at,
        )
        for job in finished[: len(self._jobs) - self._max_jobs]:
            self._jobs.pop(job.id, None)
