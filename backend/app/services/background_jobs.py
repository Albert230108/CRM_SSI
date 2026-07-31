from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable

logger = logging.getLogger(__name__)

_jobs: dict[str, dict[str, Any]] = {}

# Finished jobs are kept so a poller that arrives late can still read the result, but the
# registry is process-memory, so it can't grow without bound.
_MAX_FINISHED_JOBS = 50


def _prune_finished_jobs() -> None:
    finished = [
        (job.get("completed_at"), job_id)
        for job_id, job in _jobs.items()
        if job.get("status") != "running" and job.get("completed_at") is not None
    ]
    if len(finished) <= _MAX_FINISHED_JOBS:
        return
    finished.sort()
    for _, job_id in finished[: len(finished) - _MAX_FINISHED_JOBS]:
        _jobs.pop(job_id, None)


def start_job(kind: str, awaitable: Awaitable[Any], job_id: str | None = None) -> str:
    """Run `awaitable` in the background and return a job id to poll for status.

    `job_id` may be supplied by the caller when the awaitable itself needs to know the id it
    will be filed under (e.g. to report progress against it via update_job_progress).
    """
    job_id = job_id or uuid.uuid4().hex
    _jobs[job_id] = {
        "kind": kind,
        "status": "running",
        "result": None,
        "error": None,
        "progress": {},
        "started_at": datetime.now(timezone.utc),
        "completed_at": None,
    }
    _prune_finished_jobs()

    async def _run() -> None:
        try:
            result = await awaitable
            _jobs[job_id]["result"] = result
            _jobs[job_id]["status"] = "done"
        except Exception as exc:
            logger.exception("Background job %s (%s) failed", job_id, kind)
            _jobs[job_id]["error"] = str(exc)
            _jobs[job_id]["status"] = "error"
        finally:
            _jobs[job_id]["completed_at"] = datetime.now(timezone.utc)

    task = asyncio.create_task(_run())
    _jobs[job_id]["_task"] = task
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    job = _jobs.get(job_id)
    if job is None:
        return None
    return {key: value for key, value in job.items() if key != "_task"}


def update_job_progress(job_id: str, **fields: Any) -> None:
    """Merge progress fields into a running job so pollers can render real progress.

    Tolerates an unknown job_id: a job pruned or lost to a restart must not take down the
    worker that is still reporting against it.
    """
    job = _jobs.get(job_id)
    if job is None:
        return
    progress = job.setdefault("progress", {})
    progress.update(fields)


def find_running_job(kind: str) -> str | None:
    """Return the id of an in-flight job of `kind`, if any.

    Lets callers make a job single-flight instead of letting a double-click start a second
    concurrent run of the same expensive work.
    """
    for job_id, job in _jobs.items():
        if job.get("kind") == kind and job.get("status") == "running":
            return job_id
    return None
