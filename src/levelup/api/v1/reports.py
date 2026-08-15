"""Funnel/conversion and data-quality reporting -- read-only aggregate
queries over data the app already collects. Answers "does a high score
actually predict a won deal," "which voivodeships convert best," and
"where are the coverage gaps" without the user rebuilding these views by
hand every time.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from levelup.api.v1.schemas import (
    DataQualityReportOut,
    FunnelReportOut,
    FunnelStageOut,
    ScoreBandOut,
    VoivodeshipConversionOut,
)
from levelup.core.db import get_session
from levelup.models.enrichment import EnrichmentJobItem, SchoolContact
from levelup.models.pipeline import ActivityLog, PipelineStage, PipelineState
from levelup.models.school import TARGET_SCHOOL_CONDITIONS, School
from levelup.models.score import CurrentScore, SchoolScore

router = APIRouter(prefix="/reports", tags=["reports"])

# Forward funnel order -- LOST is a branch off this line, not a rung on it.
FUNNEL_STAGE_ORDER = [
    PipelineStage.NOT_CONTACTED,
    PipelineStage.CONTACTED,
    PipelineStage.RESPONDED,
    PipelineStage.MEETING_BOOKED,
    PipelineStage.MEETING_HELD,
    PipelineStage.NEXT_STEP_AGREED,
    PipelineStage.WON,
]

SCORE_BANDS = [
    ("0-24", 0, 24),
    ("25-49", 25, 49),
    ("50-74", 50, 74),
    ("75-100", 75, 100),
]


def _reached_stage_count(session: Session, stage: PipelineStage) -> int:
    """A school "reached" a stage if it's currently there, or an activity
    log entry ever recorded a move to it -- catches schools that have since
    advanced further (or, rarely, moved back) without undercounting."""
    current = session.query(PipelineState.school_id).filter(PipelineState.stage == stage)
    passed_through = session.query(ActivityLog.school_id).filter(
        ActivityLog.activity_type == "stage_changed", ActivityLog.to_stage == stage.value
    )
    return current.union(passed_through).count()


@router.get("/funnel", response_model=FunnelReportOut)
def get_funnel_report(session: Session = Depends(get_session)):
    pipeline_total = session.query(PipelineState).count()

    stage_reached = [FunnelStageOut(stage=PipelineStage.NOT_CONTACTED.value, reached=pipeline_total)]
    for stage in FUNNEL_STAGE_ORDER[1:]:
        stage_reached.append(FunnelStageOut(stage=stage.value, reached=_reached_stage_count(session, stage)))

    lost_count = _reached_stage_count(session, PipelineStage.LOST)
    won_count = stage_reached[-1].reached
    contacted_count = next(s.reached for s in stage_reached if s.stage == PipelineStage.CONTACTED.value)
    responded_count = next(s.reached for s in stage_reached if s.stage == PipelineStage.RESPONDED.value)

    decided = won_count + lost_count
    win_rate = (won_count / decided) if decided else None
    response_rate = (responded_count / contacted_count) if contacted_count else None

    # Score correlation with outcome -- current stage only (a currently
    # won/lost school is a decided outcome regardless of what it passed
    # through on the way there).
    decided_rows = (
        session.query(PipelineState.stage, SchoolScore.total_score)
        .join(School, School.id == PipelineState.school_id)
        .outerjoin(CurrentScore, CurrentScore.school_id == School.id)
        .outerjoin(SchoolScore, SchoolScore.id == CurrentScore.score_id)
        .filter(PipelineState.stage.in_([PipelineStage.WON, PipelineStage.LOST]))
        .all()
    )
    won_scores = [r.total_score for r in decided_rows if r.stage == PipelineStage.WON and r.total_score is not None]
    lost_scores = [r.total_score for r in decided_rows if r.stage == PipelineStage.LOST and r.total_score is not None]
    avg_score_won = (sum(won_scores) / len(won_scores)) if won_scores else None
    avg_score_lost = (sum(lost_scores) / len(lost_scores)) if lost_scores else None

    score_bands = []
    for label, lo, hi in SCORE_BANDS:
        in_band = [r for r in decided_rows if r.total_score is not None and lo <= r.total_score <= hi]
        won = sum(1 for r in in_band if r.stage == PipelineStage.WON)
        lost = sum(1 for r in in_band if r.stage == PipelineStage.LOST)
        total = won + lost
        score_bands.append(ScoreBandOut(band=label, total=total, won=won, lost=lost, win_rate=(won / total) if total else None))

    voi_rows = (
        session.query(School.voivodeship, PipelineState.stage, func.count().label("n"))
        .join(PipelineState, PipelineState.school_id == School.id)
        .group_by(School.voivodeship, PipelineState.stage)
        .all()
    )
    by_voi: dict[str, dict[str, int]] = {}
    for voi, stage, n in voi_rows:
        key = voi or "Unknown"
        entry = by_voi.setdefault(key, {"total": 0, "won": 0, "lost": 0})
        entry["total"] += n
        if stage == PipelineStage.WON:
            entry["won"] += n
        elif stage == PipelineStage.LOST:
            entry["lost"] += n
    voivodeship_conversion = [
        VoivodeshipConversionOut(
            voivodeship=voi,
            total=data["total"],
            won=data["won"],
            lost=data["lost"],
            win_rate=(data["won"] / (data["won"] + data["lost"])) if (data["won"] + data["lost"]) else None,
        )
        for voi, data in by_voi.items()
    ]
    voivodeship_conversion.sort(key=lambda r: r.total, reverse=True)

    return FunnelReportOut(
        stage_reached=stage_reached,
        lost_count=lost_count,
        win_rate=win_rate,
        response_rate=response_rate,
        avg_score_won=avg_score_won,
        avg_score_lost=avg_score_lost,
        score_bands=score_bands,
        voivodeship_conversion=voivodeship_conversion,
    )


@router.get("/data-quality", response_model=DataQualityReportOut)
def get_data_quality_report(session: Session = Depends(get_session)):
    library_total = session.query(School).filter(*TARGET_SCHOOL_CONDITIONS).count()

    library_attempted = (
        session.query(func.count(func.distinct(EnrichmentJobItem.school_id)))
        .join(School, School.id == EnrichmentJobItem.school_id)
        .filter(*TARGET_SCHOOL_CONDITIONS)
        .scalar()
        or 0
    )
    library_verified_contact = (
        session.query(func.count(func.distinct(SchoolContact.school_id)))
        .join(School, School.id == SchoolContact.school_id)
        .filter(*TARGET_SCHOOL_CONDITIONS, SchoolContact.contact_quality == "verified")
        .scalar()
        or 0
    )
    # "Partial" only counts a school if it has NO verified contact either --
    # otherwise a school with one verified and one partial contact (e.g.
    # director verified, English teacher only partial) would double-count
    # across both metrics instead of being represented once, by its best.
    verified_school_ids = session.query(SchoolContact.school_id).filter(SchoolContact.contact_quality == "verified")
    library_partial_contact = (
        session.query(func.count(func.distinct(SchoolContact.school_id)))
        .join(School, School.id == SchoolContact.school_id)
        .filter(
            *TARGET_SCHOOL_CONDITIONS,
            SchoolContact.contact_quality == "partial",
            SchoolContact.school_id.notin_(verified_school_ids),
        )
        .scalar()
        or 0
    )

    pipeline_total = session.query(PipelineState).count()
    active_stages = [
        s for s in PipelineStage if s not in (PipelineStage.WON, PipelineStage.LOST)
    ]
    pipeline_active_total = session.query(PipelineState).filter(PipelineState.stage.in_(active_stages)).count()

    pipeline_verified_contact = (
        session.query(func.count(func.distinct(SchoolContact.school_id)))
        .join(PipelineState, PipelineState.school_id == SchoolContact.school_id)
        .filter(SchoolContact.contact_quality == "verified")
        .scalar()
        or 0
    )
    pipeline_partial_contact = (
        session.query(func.count(func.distinct(SchoolContact.school_id)))
        .join(PipelineState, PipelineState.school_id == SchoolContact.school_id)
        .filter(
            SchoolContact.contact_quality == "partial",
            SchoolContact.school_id.notin_(verified_school_ids),
        )
        .scalar()
        or 0
    )
    pipeline_attempted = (
        session.query(func.count(func.distinct(EnrichmentJobItem.school_id)))
        .join(PipelineState, PipelineState.school_id == EnrichmentJobItem.school_id)
        .scalar()
        or 0
    )
    pipeline_no_follow_up = (
        session.query(PipelineState)
        .filter(PipelineState.stage.in_(active_stages), PipelineState.next_action_date.is_(None))
        .count()
    )

    stale_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=14)
    last_activity_subq = (
        session.query(ActivityLog.school_id, func.max(ActivityLog.occurred_at).label("last_activity_at"))
        .group_by(ActivityLog.school_id)
        .subquery()
    )
    pipeline_stale_14d = (
        session.query(PipelineState)
        .outerjoin(last_activity_subq, last_activity_subq.c.school_id == PipelineState.school_id)
        .filter(
            PipelineState.stage.in_(active_stages),
            (last_activity_subq.c.last_activity_at.is_(None))
            | (last_activity_subq.c.last_activity_at < stale_cutoff),
        )
        .count()
    )

    enrichment_items_success = session.query(EnrichmentJobItem).filter(EnrichmentJobItem.status == "success").count()
    enrichment_items_failed = session.query(EnrichmentJobItem).filter(EnrichmentJobItem.status == "failed").count()
    enrichment_items_total = enrichment_items_success + enrichment_items_failed

    return DataQualityReportOut(
        library_total=library_total,
        library_enriched_attempted=library_attempted,
        library_never_attempted=library_total - library_attempted,
        library_verified_contact=library_verified_contact,
        library_partial_contact=library_partial_contact,
        pipeline_total=pipeline_total,
        pipeline_active_total=pipeline_active_total,
        pipeline_missing_verified_contact=pipeline_total - pipeline_verified_contact,
        pipeline_partial_contact=pipeline_partial_contact,
        pipeline_never_enriched=pipeline_total - pipeline_attempted,
        pipeline_no_follow_up=pipeline_no_follow_up,
        pipeline_stale_14d=pipeline_stale_14d,
        enrichment_items_total=enrichment_items_total,
        enrichment_items_success=enrichment_items_success,
        enrichment_items_failed=enrichment_items_failed,
        enrichment_success_rate=(enrichment_items_success / enrichment_items_total) if enrichment_items_total else None,
    )
