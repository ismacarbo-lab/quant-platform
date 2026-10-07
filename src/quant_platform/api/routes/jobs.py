"""Background job status."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from quant_platform.api.deps import get_jobs
from quant_platform.api.jobs import JobRegistry

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, object]:
    return {
        "jobs": [
            job.as_mapping(include_result=False) for job in jobs.recent(limit=limit)
        ]
    }


@router.get("/{job_id}")
def job_detail(
    job_id: str, jobs: Annotated[JobRegistry, Depends(get_jobs)]
) -> dict[str, object]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.as_mapping()
