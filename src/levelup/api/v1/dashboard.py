"""Aggregate read-only views over Library + Pipeline for the landing
dashboard. Never mutates anything -- pure summary queries."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from levelup.api.v1.schemas import DashboardSummaryOut, RecentActivityOut, SchoolOut
from levelup.api.v1.schools import _to_out
from levelup.core.db import get_session
from levelup.models.pipeline import ActivityLog, PipelineState
from levelup.models.school import School
from levelup.models.score import CurrentScore, SchoolScore

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# There's no stored quality tier anymore (schools are compared by their raw
# 0-100 total_score, colour-graded continuously in the UI) -- this is just
# the cutoff for the dashboard's "great leads waiting" stat.
HIGH_SCORE_THRESHOLD = 70


@router.get("/summary", response_model=DashboardSummaryOut)
def get_summary(session: Session = Depends(get_session)):
    library_total = session.query(School).filter(School.is_active.is_(True)).count()

    library_by_level = {
        level.value: count
        for level, count in session.query(School.level, func.count(School.id))
        .filter(School.is_active.is_(True))
        .group_by(School.level)
        .all()
    }

    scored_total = (
        session.query(func.count(func.distinct(CurrentScore.school_id)))
        .join(School, School.id == CurrentScore.school_id)
        .filter(School.is_active.is_(True))
        .scalar()
    ) or 0
    unscored_total = library_total - scored_total

    adult_education_total = (
        session.query(School)
        .filter(School.is_active.is_(True), School.is_adult_education.is_(True))
        .count()
    )

    pipeline_total = session.query(PipelineState).count()
    stage_counts = {
        stage.value: count
        for stage, count in session.query(PipelineState.stage, func.count(PipelineState.school_id))
        .group_by(PipelineState.stage)
        .all()
    }

    high_score_not_contacted = (
        session.query(func.count(func.distinct(School.id)))
        .join(CurrentScore, CurrentScore.school_id == School.id)
        .join(SchoolScore, SchoolScore.id == CurrentScore.score_id)
        .outerjoin(PipelineState, PipelineState.school_id == School.id)
        .filter(
            School.is_active.is_(True),
            SchoolScore.total_score >= HIGH_SCORE_THRESHOLD,
            PipelineState.school_id.is_(None),
        )
        .scalar()
    ) or 0

    return DashboardSummaryOut(
        library_total=library_total,
        library_by_level=library_by_level,
        scored_total=scored_total,
        unscored_total=unscored_total,
        adult_education_total=adult_education_total,
        pipeline_total=pipeline_total,
        stage_counts=stage_counts,
        high_score_not_contacted=high_score_not_contacted,
    )


@router.get("/recent-activity", response_model=list[RecentActivityOut])
def get_recent_activity(session: Session = Depends(get_session), limit: int = Query(10, ge=1, le=100)):
    rows = (
        session.query(ActivityLog, School.name, School.city)
        .join(School, School.id == ActivityLog.school_id)
        .order_by(ActivityLog.occurred_at.desc())
        .limit(limit)
        .all()
    )
    return [
        RecentActivityOut(
            id=log.id,
            school_id=log.school_id,
            school_name=name,
            school_city=city,
            activity_type=log.activity_type,
            from_stage=log.from_stage,
            to_stage=log.to_stage,
            note=log.note,
            occurred_at=log.occurred_at,
        )
        for log, name, city in rows
    ]


@router.get("/top-leads", response_model=list[SchoolOut])
def get_top_leads(session: Session = Depends(get_session), limit: int = Query(10, ge=1, le=50)):
    rows = (
        session.query(School, SchoolScore)
        .join(CurrentScore, CurrentScore.school_id == School.id)
        .join(SchoolScore, SchoolScore.id == CurrentScore.score_id)
        .outerjoin(PipelineState, PipelineState.school_id == School.id)
        .filter(School.is_active.is_(True), PipelineState.school_id.is_(None))
        .order_by(SchoolScore.total_score.desc())
        .limit(limit)
        .all()
    )
    return [_to_out(session, school, score) for school, score in rows]
