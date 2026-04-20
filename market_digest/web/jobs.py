"""In-memory job tracker for research requests.

Jobs are keyed by a UUID. Status lifecycle: pending -> running -> done|failed.
Lost on server restart by design — clients re-request if needed.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

JobStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class Job:
    job_id: str
    ticker: str
    date: str
    status: JobStatus = "pending"
    output_url: str | None = None
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None


class JobTracker:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, ticker: str, date: str) -> Job:
        job = Job(job_id=str(uuid.uuid4()), ticker=ticker, date=date)
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def find_active(self, ticker: str, date: str) -> Job | None:
        for j in self._jobs.values():
            if j.ticker == ticker and j.date == date and j.status in ("pending", "running"):
                return j
        return None

    def mark_running(self, job_id: str) -> None:
        j = self._jobs[job_id]
        j.status = "running"

    def mark_done(self, job_id: str, output_url: str) -> None:
        j = self._jobs[job_id]
        j.status = "done"
        j.output_url = output_url
        j.finished_at = datetime.now(timezone.utc)

    def mark_failed(self, job_id: str, error: str) -> None:
        j = self._jobs[job_id]
        j.status = "failed"
        j.error = error
        j.finished_at = datetime.now(timezone.utc)

    def active(self) -> list[Job]:
        return [j for j in self._jobs.values() if j.status in ("pending", "running")]
