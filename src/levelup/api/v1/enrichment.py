from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from levelup.api.v1.schemas import EnrichmentJobOut, EnrichmentJobRequest
from levelup.api.v1.schools import _apply_filters
from levelup.core.db import get_session
from levelup.core.security import get_current_user
from levelup.models.enrichment import EnrichmentJob, EnrichmentJobItem
from levelup.models.school import School
from levelup.models.score import CurrentScore, SchoolScore
from levelup.models.user import User
from levelup.services.enrichment.jobs import cancel_job, create_job, run_job

router = APIRouter(prefix="/enrichment-jobs", tags=["enrichment"])


@router.post("", response_model=EnrichmentJobOut, status_code=202)
def start_enrichment_job(
    body: EnrichmentJobRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    # Mirror /pipeline/pull: accept either an explicit id list (checkbox
    # selection) or a filter set, so a whole filtered Library segment can be
    # enriched at once -- highest-score-first, capped by an optional limit --
    # rather than being bounded by whatever fit on the current page.
    if body.school_ids is not None:
        school_ids = body.school_ids
    elif body.filters is not None:
        query = _apply_filters(
            session.query(School.id)
            .outerjoin(CurrentScore, CurrentScore.school_id == School.id)
            .outerjoin(SchoolScore, SchoolScore.id == CurrentScore.score_id),
            **body.filters,
        )
        query = query.order_by(SchoolScore.total_score.desc().nulls_last())
        if body.limit is not None:
            query = query.limit(body.limit)
        school_ids = [row[0] for row in query.all()]
    else:
        raise HTTPException(400, "Provide either school_ids or filters")

    if not school_ids:
        raise HTTPException(400, "No schools matched -- nothing to enrich")

    job = create_job(session, school_ids, requested_by=user.id)
    background_tasks.add_task(run_job, job.id)
    return job


@router.get("", response_model=list[EnrichmentJobOut])
def list_jobs(session: Session = Depends(get_session), status: str | None = None):
    query = session.query(EnrichmentJob).options(joinedload(EnrichmentJob.items).joinedload(EnrichmentJobItem.school))
    if status:
        query = query.filter(EnrichmentJob.status == status)
    return query.order_by(EnrichmentJob.requested_at.desc()).all()


@router.get("/{job_id}", response_model=EnrichmentJobOut)
def get_job(job_id: int, session: Session = Depends(get_session)):
    return (
        session.query(EnrichmentJob)
        .options(joinedload(EnrichmentJob.items).joinedload(EnrichmentJobItem.school))
        .filter_by(id=job_id)
        .one()
    )


@router.post("/{job_id}/cancel", response_model=EnrichmentJobOut)
def cancel_enrichment_job(job_id: int, session: Session = Depends(get_session)):
    cancel_job(session, job_id)
    return (
        session.query(EnrichmentJob)
        .options(joinedload(EnrichmentJob.items).joinedload(EnrichmentJobItem.school))
        .filter_by(id=job_id)
        .one()
    )
