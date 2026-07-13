from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable

logger = logging.getLogger(__name__)

_jobs: dict[str, dict[str, Any]] = {}


def start_job(kind: str, awaitable: Awaitable[Any]) -> str:
    """Run `awaitable` in the background and return a job id to poll for status."""
    job_id = uuid.uuid4().hex
    _jobs[job_id] = {
        "kind": kind,
        "status": "running",
        "result": None,
        "error": None,
        "started_at": datetime.now(timezone.utc),
        "completed_at": None,
    }

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
