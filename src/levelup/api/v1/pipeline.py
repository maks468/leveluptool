from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from levelup.api.v1.schemas import (
    ActivityLogCreate,
    ActivityLogOut,
    BulkActionResult,
    BulkStageChangeRequest,
    MapSchoolOut,
    PipelineListOut,
    PipelineSchoolOut,
    PullIntoPipelineRequest,
    PullIntoPipelineResult,
    QueueEntryOut,
    SetFollowUpRequest,
    StageChangeRequest,
)
from levelup.api.v1.schools import _apply_filters, _compute_enrichment_levels, _to_out
from levelup.core.db import get_session
from levelup.core.security import get_current_user
from levelup.models.crm import SchoolTag
from levelup.models.pipeline import ActivityLog, PipelineStage, PipelineState
from levelup.models.school import School
from levelup.models.score import CurrentScore, SchoolScore
from levelup.models.user import User
from levelup.services.pipeline.activity import log_activity
from levelup.services.pipeline.geocoding import backfill_missing_coordinates
from levelup.services.pipeline.stages import change_stage, pull_into_pipeline

router = APIRouter(tags=["pipeline"])

PIPELINE_SORTABLE_FIELDS = {
    "name": School.name,
    "city": School.city,
    "students": School.student_count,
    "score": SchoolScore.total_score,
    "stage_updated_at": PipelineState.stage_updated_at,
    "entered_pipeline_at": PipelineState.entered_pipeline_at,
    "next_action_date": PipelineState.next_action_date,
}


def _pipeline_school_out(
    session: Session, school: School, state: PipelineState, enrichment_level: str | None = None
) -> PipelineSchoolOut:
    score = (
        session.query(SchoolScore)
        .join(CurrentScore, CurrentScore.score_id == SchoolScore.id)
        .filter(CurrentScore.school_id == school.id)
        .one_or_none()
    )
    base = _to_out(session, school, score, enrichment_level)
    return PipelineSchoolOut(
        **base.model_dump(exclude={"stage"}),
        stage=state.stage.value,
        entered_pipeline_at=state.entered_pipeline_at,
        stage_updated_at=state.stage_updated_at,
    )


def _apply_pipeline_filters(
    query,
    *,
    stage: str | None = None,
    q: str | None = None,
    voivodeship: str | None = None,
    city: str | None = None,
    tag_id: int | None = None,
    score_min: int | None = None,
    score_max: int | None = None,
    score_include_unscored: bool = True,
):
    """The pipeline's own filter set (distinct from the Library's
    _apply_filters): assumes the query is already joined to PipelineState.
    Shared by the paginated list and the /pipeline/ids resolver so
    "enrich/act on everything in this view" matches exactly what the table
    shows, across all pages."""
    if stage:
        query = query.filter(PipelineState.stage == stage)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(School.name.ilike(like), School.city.ilike(like)))
    if voivodeship:
        query = query.filter(School.voivodeship == voivodeship)
    if city:
        query = query.filter(School.city == city)
    if tag_id is not None:
        query = query.join(SchoolTag, SchoolTag.school_id == School.id).filter(SchoolTag.tag_id == tag_id)
    if score_min is not None or score_max is not None:
        range_conditions = [SchoolScore.total_score.isnot(None)]
        if score_min is not None:
            range_conditions.append(SchoolScore.total_score >= score_min)
        if score_max is not None:
            range_conditions.append(SchoolScore.total_score <= score_max)
        conditions = [and_(*range_conditions)]
        if score_include_unscored:
            conditions.append(SchoolScore.total_score.is_(None))
        query = query.filter(or_(*conditions))
    return query


@router.get("/pipeline", response_model=PipelineListOut)
def list_pipeline(
    session: Session = Depends(get_session),
    stage: str | None = None,
    q: str | None = Query(None, description="Search school name or city"),
    voivodeship: str | None = None,
    city: str | None = None,
    tag_id: int | None = None,
    score_min: int | None = None,
    score_max: int | None = None,
    score_include_unscored: bool = True,
    sort: str = "stage_updated_at:desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    query = (
        session.query(School, PipelineState)
        .join(PipelineState, PipelineState.school_id == School.id)
        .outerjoin(CurrentScore, CurrentScore.school_id == School.id)
        .outerjoin(SchoolScore, SchoolScore.id == CurrentScore.score_id)
    )
    query = _apply_pipeline_filters(
        query,
        stage=stage,
        q=q,
        voivodeship=voivodeship,
        city=city,
        tag_id=tag_id,
        score_min=score_min,
        score_max=score_max,
        score_include_unscored=score_include_unscored,
    )

    total = query.count()

    field_name, _, direction = sort.partition(":")
    sort_col = PIPELINE_SORTABLE_FIELDS.get(field_name, PipelineState.stage_updated_at)
    sort_col = sort_col.desc().nulls_last() if direction != "asc" else sort_col.asc().nulls_last()
    query = query.order_by(sort_col)

    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    stage_counts = {
        s.value: count
        for s, count in session.query(PipelineState.stage, func.count(PipelineState.school_id))
        .group_by(PipelineState.stage)
        .all()
    }

    enrichment_levels = _compute_enrichment_levels(session, [school.id for school, _ in rows])
    results = [_pipeline_school_out(session, school, state, enrichment_levels.get(school.id)) for school, state in rows]
    return PipelineListOut(total=total, page=page, page_size=page_size, stage_counts=stage_counts, items=results)


@router.get("/pipeline/ids")
def list_pipeline_ids(
    session: Session = Depends(get_session),
    stage: str | None = None,
    q: str | None = Query(None, description="Search school name or city"),
    voivodeship: str | None = None,
    city: str | None = None,
    tag_id: int | None = None,
    score_min: int | None = None,
    score_max: int | None = None,
    score_include_unscored: bool = True,
):
    """Every school id in the pipeline matching the given filters, across
    all pages (highest score first) -- lets the UI act on a whole filtered
    pipeline view (e.g. "enrich all N") without being capped at one page."""
    query = (
        session.query(School.id)
        .join(PipelineState, PipelineState.school_id == School.id)
        .outerjoin(CurrentScore, CurrentScore.school_id == School.id)
        .outerjoin(SchoolScore, SchoolScore.id == CurrentScore.score_id)
    )
    query = _apply_pipeline_filters(
        query,
        stage=stage,
        q=q,
        voivodeship=voivodeship,
        city=city,
        tag_id=tag_id,
        score_min=score_min,
        score_max=score_max,
        score_include_unscored=score_include_unscored,
    )
    query = query.order_by(SchoolScore.total_score.desc().nulls_last())
    return {"ids": [row[0] for row in query.all()]}


@router.get("/pipeline/tasks-due", response_model=list[PipelineSchoolOut])
def list_tasks_due(
    session: Session = Depends(get_session),
    within_days: int = Query(7, ge=0, description="Include follow-ups due within this many days (overdue always included)"),
):
    """Pulls together every pipeline school with a follow-up date into one
    "what's due today/this week" list -- previously next_action_date was
    only visible one school at a time in the detail drawer, with no way to
    see what's actually due across the whole active pipeline."""
    horizon = datetime.now(timezone.utc) + timedelta(days=within_days)
    rows = (
        session.query(School, PipelineState)
        .join(PipelineState, PipelineState.school_id == School.id)
        .filter(PipelineState.next_action_date.isnot(None), PipelineState.next_action_date <= horizon)
        .order_by(PipelineState.next_action_date.asc())
        .all()
    )
    enrichment_levels = _compute_enrichment_levels(session, [school.id for school, _ in rows])
    return [_pipeline_school_out(session, school, state, enrichment_levels.get(school.id)) for school, state in rows]


@router.get("/pipeline/queue", response_model=list[QueueEntryOut])
def list_queue(
    session: Session = Depends(get_session),
    limit: int = Query(50, ge=1, le=500),
):
    """Ranks every active (non-won/non-lost) pipeline school into one "who
    do I contact next" list: overdue follow-up > due-today follow-up >
    not-yet-contacted (by score) > everything else in progress (by score,
    then staleness). Replaces rebuilding this view by hand via filters."""
    rows = (
        session.query(School, PipelineState)
        .join(PipelineState, PipelineState.school_id == School.id)
        .filter(PipelineState.stage.notin_([PipelineStage.WON, PipelineStage.LOST]))
        .all()
    )

    last_activity_by_school = dict(
        session.query(ActivityLog.school_id, func.max(ActivityLog.occurred_at)).group_by(ActivityLog.school_id).all()
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today_start = datetime(now.year, now.month, now.day)
    today_end = today_start + timedelta(days=1)

    def rank(state: PipelineState, school_id: int, score_val: int | None, last_activity_at: datetime | None):
        effective_score = score_val if score_val is not None else -1
        if state.next_action_date is not None and state.next_action_date < today_start:
            days_overdue = (today_start.date() - state.next_action_date.date()).days
            reason = "Follow-up overdue by 1 day" if days_overdue == 1 else f"Follow-up overdue by {days_overdue} days"
            return (0, -effective_score, state.next_action_date), reason
        if state.next_action_date is not None and state.next_action_date < today_end:
            return (1, -effective_score, state.next_action_date), "Follow-up due today"
        if state.stage == PipelineStage.NOT_CONTACTED:
            reason = f"Not yet contacted — score {score_val}/100" if score_val is not None else "Not yet contacted — not yet scored"
            return (2, -effective_score, school_id), reason
        if last_activity_at is None:
            return (3, -effective_score, school_id), "No activity logged yet"
        stale_days = (now - last_activity_at).days
        reason = "Active today" if stale_days <= 0 else f"No activity in {stale_days}d"
        return (3, -effective_score, -stale_days), reason

    enrichment_levels = _compute_enrichment_levels(session, [school.id for school, _ in rows])
    entries = []
    for school, state in rows:
        base = _pipeline_school_out(session, school, state, enrichment_levels.get(school.id))
        last_activity_at = last_activity_by_school.get(school.id)
        key, reason = rank(state, school.id, base.score.total_score if base.score else None, last_activity_at)
        entries.append((key, base, last_activity_at, reason))

    entries.sort(key=lambda e: e[0])
    entries = entries[:limit]

    return [
        QueueEntryOut(**base.model_dump(), last_activity_at=last_activity_at, queue_reason=reason)
        for _, base, last_activity_at, reason in entries
    ]


@router.get("/pipeline/map", response_model=list[MapSchoolOut])
def get_map_schools(session: Session = Depends(get_session)):
    """Backfills missing coordinates on demand -- scoped only to schools
    actually in the pipeline, never the whole 25k-school registry -- then
    returns every plottable pipeline school with its latest activity."""
    rows = (
        session.query(School, PipelineState)
        .join(PipelineState, PipelineState.school_id == School.id)
        .all()
    )
    schools = [school for school, _ in rows]
    backfill_missing_coordinates(session, schools)

    school_ids = [school.id for school in schools]
    activity_rows = (
        session.query(ActivityLog)
        .filter(ActivityLog.school_id.in_(school_ids))
        .order_by(ActivityLog.occurred_at.desc())
        .all()
    )
    last_activity_by_school: dict[int, ActivityLog] = {}
    for entry in activity_rows:
        last_activity_by_school.setdefault(entry.school_id, entry)

    results = []
    for school, state in rows:
        if school.latitude is None or school.longitude is None:
            continue
        score = (
            session.query(SchoolScore)
            .join(CurrentScore, CurrentScore.score_id == SchoolScore.id)
            .filter(CurrentScore.school_id == school.id)
            .one_or_none()
        )
        last_activity = last_activity_by_school.get(school.id)
        results.append(
            MapSchoolOut(
                id=school.id,
                name=school.name,
                city=school.city,
                latitude=school.latitude,
                longitude=school.longitude,
                stage=state.stage.value,
                score=score.total_score if score else None,
                director_name=school.director_name,
                english_teacher_name=school.english_teacher_name,
                last_activity_at=last_activity.occurred_at if last_activity else None,
                last_note=last_activity.note if last_activity else None,
            )
        )
    return results


@router.patch("/schools/{school_id}/follow-up", response_model=PipelineSchoolOut)
def set_follow_up(
    school_id: int,
    body: SetFollowUpRequest,
    session: Session = Depends(get_session),
):
    state = session.query(PipelineState).filter_by(school_id=school_id).one_or_none()
    if state is None:
        raise HTTPException(404, "School is not in the pipeline")
    state.next_action_note = body.next_action_note
    state.next_action_date = body.next_action_date
    session.commit()
    school = session.query(School).filter_by(id=school_id).one()
    return _pipeline_school_out(session, school, state)


@router.post("/pipeline/pull", response_model=PullIntoPipelineResult)
def pull(
    body: PullIntoPipelineRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if body.school_ids is not None:
        school_ids = body.school_ids
    elif body.filters is not None:
        query = _apply_filters(
            session.query(School.id).outerjoin(CurrentScore, CurrentScore.school_id == School.id).outerjoin(
                SchoolScore, SchoolScore.id == CurrentScore.score_id
            ),
            **body.filters,
        )
        query = query.order_by(SchoolScore.total_score.desc().nulls_last())
        if body.limit is not None:
            query = query.limit(body.limit)
        school_ids = [row[0] for row in query.all()]
    else:
        raise HTTPException(400, "Provide either school_ids or filters")

    result = pull_into_pipeline(session, school_ids, owner_id=user.id, actor_id=user.id)
    return PullIntoPipelineResult(**result)


@router.patch("/schools/{school_id}/stage", response_model=PipelineSchoolOut)
def set_stage(
    school_id: int,
    body: StageChangeRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    try:
        new_stage = PipelineStage(body.stage)
    except ValueError:
        raise HTTPException(400, f"Unknown stage: {body.stage}")

    state = change_stage(session, school_id, new_stage, actor_id=user.id)
    school = session.query(School).filter_by(id=school_id).one()
    return _pipeline_school_out(session, school, state)


@router.patch("/pipeline/bulk-stage", response_model=BulkActionResult)
def bulk_set_stage(
    body: BulkStageChangeRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    try:
        new_stage = PipelineStage(body.stage)
    except ValueError:
        raise HTTPException(400, f"Unknown stage: {body.stage}")

    in_pipeline = {
        row.school_id
        for row in session.query(PipelineState.school_id).filter(PipelineState.school_id.in_(body.school_ids)).all()
    }
    updated = 0
    for school_id in body.school_ids:
        if school_id not in in_pipeline:
            continue
        change_stage(session, school_id, new_stage, actor_id=user.id)
        updated += 1
    return BulkActionResult(updated=updated)


@router.get("/schools/{school_id}/activity", response_model=list[ActivityLogOut])
def get_activity(school_id: int, session: Session = Depends(get_session)):
    rows = (
        session.query(ActivityLog)
        .filter_by(school_id=school_id)
        .order_by(ActivityLog.occurred_at.desc())
        .all()
    )
    return rows


@router.post("/schools/{school_id}/activity", response_model=ActivityLogOut)
def add_activity_note(
    school_id: int,
    body: ActivityLogCreate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    entry = log_activity(session, school_id=school_id, activity_type="note", actor_id=user.id, note=body.note)
    session.commit()
    return entry
