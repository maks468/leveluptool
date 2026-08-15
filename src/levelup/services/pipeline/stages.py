from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from levelup.models.campaign import CampaignSchool
from levelup.models.pipeline import ActivityType, PipelineStage, PipelineState
from levelup.models.school import School
from levelup.services.automation.hooks import on_stage_changed
from levelup.services.pipeline.activity import log_activity


def pull_into_pipeline(
    session: Session,
    school_ids: list[int],
    owner_id: int,
    actor_id: int,
    pull_criteria: str | None = None,
) -> dict[str, int]:
    already = {
        row.school_id
        for row in session.query(PipelineState).filter(PipelineState.school_id.in_(school_ids)).all()
    }
    # Campaign members are skipped, not re-pulled -- a school in a campaign
    # was deliberately parked there, and silently pulling it back is exactly
    # the double-contact path campaigns exist to close. Getting one back is
    # the campaign page's explicit return-to-pipeline action.
    in_campaign = {
        row.school_id
        for row in session.query(CampaignSchool.school_id)
        .filter(CampaignSchool.school_id.in_(school_ids))
        .all()
    }
    new_ids = [sid for sid in school_ids if sid not in already and sid not in in_campaign]

    for school_id in new_ids:
        session.add(
            PipelineState(
                school_id=school_id,
                owner_id=owner_id,
                stage=PipelineStage.NOT_CONTACTED,
                pull_criteria=pull_criteria,
            )
        )
        log_activity(
            session,
            school_id=school_id,
            activity_type=ActivityType.PULLED_INTO_PIPELINE.value,
            actor_id=actor_id,
            metadata={"pull_criteria": pull_criteria} if pull_criteria else {},
        )
    session.commit()
    return {
        "pulled_new": len(new_ids),
        "already_in_pipeline": len(already),
        "already_in_campaign": len(in_campaign),
    }


def change_stage(session: Session, school_id: int, new_stage: PipelineStage, actor_id: int) -> PipelineState:
    state = session.query(PipelineState).filter_by(school_id=school_id).one()
    old_stage = state.stage
    state.stage = new_stage
    state.stage_updated_at = datetime.now(timezone.utc)
    log_activity(
        session,
        school_id=school_id,
        activity_type=ActivityType.STAGE_CHANGED.value,
        actor_id=actor_id,
        from_stage=old_stage.value,
        to_stage=new_stage.value,
    )
    session.commit()
    on_stage_changed(school_id=school_id, from_stage=old_stage.value, to_stage=new_stage.value)
    return state
