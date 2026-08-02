"""Persisted Audel jobs that outlive an individual mobile HTTP request."""

import json
import re
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.budget.db import get_session
from app.budget.models import AgentJob
from app.budget.services.batch_categorization import run_job

router = APIRouter(prefix="/api/assistant/jobs", tags=["copilot"])
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class CategorizeUnbudgetedRequest(BaseModel):
    month: str
    timezone: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=128)


class AgentJobResponse(BaseModel):
    id: str
    kind: str
    status: str
    stage: str
    total: int
    completed: int
    message: str | None = None
    categorized: int | None = None
    remaining: int | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


def _response(job: AgentJob) -> AgentJobResponse:
    result = {}
    if job.status == "completed" and job.result_json:
        try:
            result = json.loads(job.result_json)
        except json.JSONDecodeError:
            result = {}
    return AgentJobResponse(
        id=job.id,
        kind=job.kind,
        status=job.status,
        stage=job.stage,
        total=job.total,
        completed=job.completed,
        message=result.get("message"),
        categorized=result.get("categorized"),
        remaining=result.get("remaining"),
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post("/categorize-unbudgeted", response_model=AgentJobResponse, status_code=202)
def create_categorization_job(
    body: CategorizeUnbudgetedRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    if not MONTH_PATTERN.fullmatch(body.month):
        raise HTTPException(status_code=422, detail="month must use YYYY-MM")
    existing = session.exec(
        select(AgentJob).where(AgentJob.idempotency_key == body.idempotency_key)
    ).first()
    if existing is not None:
        return _response(existing)

    job = AgentJob(
        id=str(uuid4()),
        kind="categorize_unbudgeted",
        idempotency_key=body.idempotency_key,
        result_json=json.dumps({
            "month": body.month,
            "timezone": body.timezone,
        }),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    # Use the request session's bind so dependency-overridden test databases and
    # alternate deployments execute the worker against the same database.
    background_tasks.add_task(run_job, job.id, session.get_bind())
    return _response(job)


@router.get("/{job_id}", response_model=AgentJobResponse)
def get_job(job_id: str, session: Session = Depends(get_session)):
    job = session.get(AgentJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Agent job not found")
    return _response(job)
